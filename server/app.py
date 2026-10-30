import os, json, uuid
import redis
from rq import Queue
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import time
import pipeline
import stage2
import runner
import re
import requests

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
r = redis.Redis(decode_responses=True)
q = Queue("smash-bender", connection=redis.Redis())
TOKEN = os.environ.get("SB_TOKEN", "")
FILES = {"mix.mp3", "bent_vocal.wav", "bent_vocal.mp3", "sung_vocal.mp3"}


def check(req):
    if TOKEN and req.headers.get("x-sb-key") != TOKEN:
        raise HTTPException(401, "bad key")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/jobs")
async def create(req: Request):
    check(req)
    body = await req.json()
    if not body.get("ccmixter") and not (body.get("song1") and body.get("song2")):
        raise HTTPException(400, "song1 and song2, or ccmixter, required")
    job = uuid.uuid4().hex[:10]
    d = pipeline.job_dir(job)
    meta = {"song1": body.get("song1"), "song2": body.get("song2"),
            "ccmixter": body.get("ccmixter", ""), "seconds": int(body.get("seconds", 30) or 0),
            "overlay": bool(body.get("overlay")),
            "voice_id": body.get("voice_id") or os.environ.get("ELEVENLABS_VOICE_ID", "")}
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"))
    pipeline.set_state(job, status="queued", progress="queued", rev=0)
    q.enqueue(pipeline.run_job, job, job_timeout=3600)
    return {"job": job}


@app.get("/jobs/{job}")
def status(job: str, req: Request):
    check(req)
    s = r.hgetall("sb:job:" + job)
    if not s:
        raise HTTPException(404, "no job")
    return s


@app.get("/jobs/{job}/plan")
def plan(job: str, req: Request):
    check(req)
    p = os.path.join(pipeline.DATA, "jobs", job, "plan.json")
    if not os.path.exists(p):
        raise HTTPException(404, "no plan yet")
    return json.load(open(p))


@app.post("/jobs/{job}/render")
async def rerender(job: str, req: Request):
    check(req)
    body = await req.json()
    d = os.path.join(pipeline.DATA, "jobs", job)
    if not os.path.exists(os.path.join(d, "plan.json")):
        raise HTTPException(404, "no plan yet")
    if "items" in body:
        json.dump({"items": body["items"]}, open(os.path.join(d, "plan.json"), "w"))
    if "voice_id" in body:
        meta = json.load(open(os.path.join(d, "meta.json")))
        meta["voice_id"] = body["voice_id"]
        json.dump(meta, open(os.path.join(d, "meta.json"), "w"))
    pipeline.set_state(job, status="queued", progress="queued")
    q.enqueue(pipeline.rerender, job, job_timeout=1800)
    return {"job": job}


@app.get("/files/{job}/{name}")
def files(job: str, name: str):
    if name not in FILES or not job.isalnum():
        raise HTTPException(404, "no file")
    p = os.path.join(pipeline.DATA, "jobs", job, name)
    if not os.path.exists(p):
        raise HTTPException(404, "no file")
    return FileResponse(p)


EXP = os.path.join(pipeline.DATA, "experiments")
RATINGS = os.path.join(EXP, "ratings.json")
HERE = os.path.dirname(os.path.abspath(__file__))


@app.get("/")
def home():
    return FileResponse(os.path.join(HERE, "static", "index.html"), media_type="text/html")


def load_ratings():
    try:
        return json.load(open(RATINGS))
    except (OSError, ValueError):
        return {}


@app.get("/api/experiments")
def experiments(project: str = ""):
    batches = {}
    if os.path.isdir(EXP):
        for fn in os.listdir(EXP):
            if not fn.endswith(".jsonl") or fn.endswith(".stage2.jsonl"):
                continue
            for line in open(os.path.join(EXP, fn)):
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if project and rec.get("experiment", fn[:-6]) != project:
                    continue
                key = rec.get("experiment", fn[:-6]) + "|" + rec.get("batch", rec.get("time", "")[:16])
                batches.setdefault(key, []).append(rec)
    ratings = load_ratings()
    out = []
    for key, recs in batches.items():
        recs.sort(key=lambda r: r.get("run", 0))
        for r in recs:
            r.setdefault("sample", "ABCD"[max(0, min(3, r.get("run", 1) - 1))])
            r.setdefault("audio", "/files/%s%d/mix.mp3" % (r.get("experiment", ""), r.get("run", 1)))
            r["rating"] = ratings.get(key + "|" + str(r.get("run")), 0)
        first = recs[0]
        out.append({"key": key, "experiment": first.get("experiment"), "time": first.get("time"),
                    "song_one": first.get("song_one", ""), "song_two": first.get("song_two", ""),
                    "music_key": first.get("music_key", ""), "music_bpm": first.get("music_bpm"),
                    "voice_key": first.get("voice_key", ""), "voice_bpm": first.get("voice_bpm"),
                    "samples": recs})
    out.sort(key=lambda b: b["time"] or "", reverse=True)
    return out


@app.post("/api/rate")
async def rate(req: Request):
    body = await req.json()
    stars = int(body.get("stars", 0))
    if not body.get("key") or stars < 0 or stars > 5:
        raise HTTPException(400, "key and stars 0 to 5 required")
    ratings = load_ratings()
    ratings[body["key"] + "|" + str(int(body.get("run", 0)))] = stars
    os.makedirs(EXP, exist_ok=True)
    json.dump(ratings, open(RATINGS, "w"))
    return {"ok": True}


@app.post("/api/stage2")
async def send_stage2(req: Request):
    body = await req.json()
    tool = body.get("tool", "elevenlabs")
    if tool not in stage2.TOOLS or not body.get("key") or not body.get("run"):
        raise HTTPException(400, "key, run and a known tool required")
    try:
        parent = stage2.find_parent(body["key"], int(body["run"]))
    except RuntimeError:
        raise HTTPException(404, "that sample was not found")
    job_id = uuid.uuid4().hex[:8]
    r.hset("sb:stage2:" + job_id, mapping={"status": "queued", "progress": "waiting", "key": body["key"],
                                            "run": str(int(body["run"])), "tool": tool,
                                            "tool_name": stage2.TOOLS[tool],
                                            "stage": str(int(parent.get("stage_num", 1)) + 1),
                                            "time": time.strftime("%Y-%m-%d %H:%M")})
    r.expire("sb:stage2:" + job_id, 86400)
    q.enqueue(stage2.run_stage2, job_id, body["key"], int(body["run"]), tool, job_timeout=3600)
    return {"job": job_id}


@app.get("/api/stage2")
def list_stage2(project: str = ""):
    batches = {}
    if os.path.isdir(EXP):
        for fn in os.listdir(EXP):
            if not fn.endswith(".stage2.jsonl"):
                continue
            for line in open(os.path.join(EXP, fn)):
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if project and rec.get("experiment") != project:
                    continue
                key = "s2|" + rec.get("experiment", "") + "|" + rec.get("batch", "")
                batches.setdefault(key, []).append(rec)
    ratings = load_ratings()
    out = []
    for key, recs in batches.items():
        recs.sort(key=lambda x: x.get("run", 0))
        for x in recs:
            x["rating"] = ratings.get(key + "|" + str(x.get("run")), 0)
        f = recs[0]
        out.append({"key": key, "experiment": f.get("experiment"), "time": f.get("time"), "stage": f.get("stage"),
                    "stage_name": f.get("stage_name"), "stage_num": f.get("stage_num", 2),
                    "parent_stage": f.get("parent_stage", 1), "parent_tool": f.get("parent_tool", ""),
                    "music_key": f.get("music_key", ""), "music_bpm": f.get("music_bpm"),
                    "song_one": f.get("song_one", ""),
                    "song_two": f.get("song_two", ""), "parent_sample": f.get("parent_sample"),
                    "parent_label": f.get("parent_label"), "parent_time": f.get("parent_time"), "samples": recs})
    out.sort(key=lambda b: b["time"] or "", reverse=True)
    pending = []
    for k in r.scan_iter("sb:stage2:*"):
        h = r.hgetall(k)
        if h.get("status") in ("queued", "working", "error"):
            name = h.get("key", "").split("|")[-2] if h.get("key", "").startswith("s2|") else h.get("key", "").split("|")[0]
            if not project or name == project:
                pending.append(h)
    return {"sets": out, "pending": pending}


PROJECTS = os.path.join(EXP, "projects.json")


def load_projects():
    try:
        return json.load(open(PROJECTS))
    except (OSError, ValueError):
        return {}


@app.get("/api/projects")
def projects():
    known = load_projects()
    if os.path.isdir(EXP):
        for fn in os.listdir(EXP):
            if fn.endswith(".jsonl") and not fn.endswith(".stage2.jsonl"):
                slug = fn[:-6]
                known.setdefault(slug, {"name": slug, "created": time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(os.path.join(EXP, fn))))})
    return sorted([dict(v, slug=k) for k, v in known.items()], key=lambda p: p.get("created", ""), reverse=True)


@app.post("/api/projects")
async def new_project(req: Request):
    body = await req.json()
    name = (body.get("name") or "").strip()
    slug = re.sub(r"[^a-z0-9]", "", name.lower())[:40]
    if not slug:
        raise HTTPException(400, "give the project a name with letters or numbers")
    known = load_projects()
    if slug in known:
        raise HTTPException(409, "a project with that name already exists")
    known[slug] = {"name": name, "created": time.strftime("%Y-%m-%d %H:%M")}
    os.makedirs(EXP, exist_ok=True)
    json.dump(known, open(PROJECTS, "w"))
    return {"slug": slug}


def ensure_project(name):
    slug = re.sub(r"[^a-z0-9]", "", (name or "").lower())[:40]
    if not slug:
        raise HTTPException(400, "give the project a name with letters or numbers")
    known = load_projects()
    if slug not in known:
        known[slug] = {"name": name.strip(), "created": time.strftime("%Y-%m-%d %H:%M")}
        os.makedirs(EXP, exist_ok=True)
        json.dump(known, open(PROJECTS, "w"))
    return slug


async def save_part(slug, part, stamp, upload=None, url=""):
    inbox = os.path.join(pipeline.DATA, "inbox")
    os.makedirs(inbox, exist_ok=True)
    source = (upload.filename if upload is not None else url.split("?")[0]) or ""
    ext = re.sub(r"[^a-z0-9]", "", os.path.splitext(source)[1].lower())[:5] or "audio"
    fname = "%s_%s_%s.%s" % (slug, part, stamp, ext)
    path = os.path.join(inbox, fname)
    if upload is not None:
        with open(path, "wb") as fh:
            while True:
                chunk = await upload.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
    else:
        if not url.startswith(("http://", "https://")):
            raise HTTPException(400, "the %s link must start with http or https" % part)
        try:
            with requests.get(url, headers=pipeline.BROWSER, stream=True, timeout=120) as res:
                res.raise_for_status()
                with open(path, "wb") as fh:
                    for chunk in res.iter_content(1 << 16):
                        fh.write(chunk)
        except requests.RequestException as e:
            raise HTTPException(400, "could not download the %s track: %s" % (part, str(e)[:120]))
    if os.path.getsize(path) < 1000:
        raise HTTPException(400, "the %s track is empty or too small" % part)
    return fname


def queue_experiment(slug, music, voice, seconds, song_one, song_two, source):
    job_id = uuid.uuid4().hex[:8]
    r.hset("sb:stage2:" + job_id, mapping={"status": "queued", "progress": "waiting", "key": slug + "|new",
                                            "run": "0", "tool": "experiment", "tool_name": "New experiment",
                                            "stage": "1", "time": time.strftime("%Y-%m-%d %H:%M"), "source": source})
    r.expire("sb:stage2:" + job_id, 86400)
    q.enqueue(runner.run_experiment, job_id, music, voice, slug, max(10, min(240, int(seconds or 45))),
              song_one.strip() or music, song_two.strip() or voice, job_timeout=3600)
    return job_id


@app.post("/api/run")
async def start_run(project: str = Form(...), song_one: str = Form(""), song_two: str = Form(""),
                    seconds: int = Form(45), instrumental: UploadFile = File(...), acapella: UploadFile = File(...)):
    slug = re.sub(r"[^a-z0-9]", "", project.lower())
    if not slug:
        raise HTTPException(400, "pick a project first")
    stamp = time.strftime("%m%d%H%M%S")
    music = await save_part(slug, "music", stamp, upload=instrumental)
    voice = await save_part(slug, "voice", stamp, upload=acapella)
    return {"job": queue_experiment(slug, music, voice, seconds, song_one, song_two, "page")}


@app.post("/api/import")
async def import_project(project: str = Form(...), song_one: str = Form(""), song_two: str = Form(""),
                         seconds: int = Form(45), source: str = Form("smash director"),
                         instrumental: UploadFile = File(None), acapella: UploadFile = File(None),
                         instrumental_url: str = Form(""), acapella_url: str = Form("")):
    """Start a project from another app: send the music and voice as files or as links."""
    if instrumental is None and not instrumental_url:
        raise HTTPException(400, "send instrumental as a file or instrumental_url as a link")
    if acapella is None and not acapella_url:
        raise HTTPException(400, "send acapella as a file or acapella_url as a link")
    slug = re.sub(r"[^a-z0-9]", "", (project or "").lower())[:40]
    if not slug:
        raise HTTPException(400, "give the project a name with letters or numbers")
    stamp = time.strftime("%m%d%H%M%S")
    music = await save_part(slug, "music", stamp, upload=instrumental, url=instrumental_url)
    voice = await save_part(slug, "voice", stamp, upload=acapella, url=acapella_url)
    ensure_project(project)
    job = queue_experiment(slug, music, voice, seconds, song_one, song_two, source[:40])
    return {"project": slug, "job": job,
            "open": "https://smash-bender.167-233-137-169.sslip.io/?project=" + slug}
