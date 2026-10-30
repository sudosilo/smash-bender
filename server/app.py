import os, json, uuid
import redis
from rq import Queue
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
