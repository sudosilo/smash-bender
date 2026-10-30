import os, json, uuid
import redis
from rq import Queue
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import time
import pipeline

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
def experiments():
    batches = {}
    if os.path.isdir(EXP):
        for fn in os.listdir(EXP):
            if not fn.endswith(".jsonl"):
                continue
            for line in open(os.path.join(EXP, fn)):
                try:
                    rec = json.loads(line)
                except ValueError:
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
