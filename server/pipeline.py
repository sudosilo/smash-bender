import os, json, hashlib, shutil, subprocess
import numpy as np
import soundfile as sf
import librosa
import pyrubberband as pyrb
import requests
import redis

DATA = os.environ.get("SB_DATA", "/opt/smash-bender/data")
PY = os.environ.get("SB_PY", "/opt/smash-bender/venv/bin/python")
SR = 44100
ASR = 22050
HOP = 256
r = redis.Redis(decode_responses=True)


def set_state(job, **kw):
    r.hset("sb:job:" + job, mapping={k: str(v) for k, v in kw.items()})


def job_dir(job):
    d = os.path.join(DATA, "jobs", job)
    os.makedirs(d, exist_ok=True)
    return d


def song_key(q):
    return hashlib.sha1(q.strip().lower().encode()).hexdigest()[:16]


def fetch_and_split(query, job, label):
    d = os.path.join(DATA, "songs", song_key(query))
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, "song.wav")
    if not os.path.exists(src):
        set_state(job, progress="downloading " + label)
        target = query if query.startswith("http") else "ytsearch1:" + query
        subprocess.run([PY, "-m", "yt_dlp", "--no-playlist", "-x", "--audio-format", "wav",
                        "--print-to-file", "%(title)s", os.path.join(d, "title.txt"),
                        "-o", os.path.join(d, "song.%(ext)s"), target], check=True)
    voc = os.path.join(d, "vocals.wav")
    inst = os.path.join(d, "instrumental.wav")
    if not (os.path.exists(voc) and os.path.exists(inst)):
        set_state(job, progress="splitting " + label)
        out = os.path.join(d, "sep")
        subprocess.run([PY, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs",
                        "--segment", "7", "-j", "1", "-o", out, src], check=True)
        shutil.move(os.path.join(out, "htdemucs", "song", "vocals.wav"), voc)
        shutil.move(os.path.join(out, "htdemucs", "song", "no_vocals.wav"), inst)
        shutil.rmtree(out, ignore_errors=True)
    title = ""
    tp = os.path.join(d, "title.txt")
    if os.path.exists(tp):
        lines = open(tp).read().strip().splitlines()
        title = lines[0] if lines else ""
    return d, title


def find_notes(path):
    y, _ = librosa.load(path, sr=ASR, mono=True)
    f0, voiced, _ = librosa.pyin(y, fmin=65, fmax=1000, sr=ASR, hop_length=HOP)
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    gate = max(1e-4, float(np.percentile(rms, 60)) * 0.25)
    midi = librosa.hz_to_midi(np.where(np.isnan(f0), 1.0, f0))
    ft = HOP / ASR
    notes, cur = [], None
    for i in range(len(f0)):
        ok = bool(voiced[i]) and not np.isnan(f0[i]) and rms[min(i, len(rms) - 1)] > gate
        if ok and cur and abs(midi[i] - np.median(cur["m"])) < 0.8:
            cur["m"].append(midi[i]); cur["e"] = i
            continue
        if cur and (cur["e"] - cur["s"] + 1) * ft >= 0.06:
            notes.append(cur)
        cur = {"s": i, "e": i, "m": [midi[i]]} if ok else None
    if cur and (cur["e"] - cur["s"] + 1) * ft >= 0.06:
        notes.append(cur)
    return [{"start": round(n["s"] * ft, 4), "end": round((n["e"] + 1) * ft, 4),
             "midi": round(float(np.median(n["m"])), 2)} for n in notes]


def build_plan(target_notes, source_notes):
    n, m = len(target_notes), len(source_notes)
    items = []
    if n == 0 or m == 0:
        return items
    for i, t in enumerate(target_notes):
        s = source_notes[min(m - 1, i * m // n)]
        items.append({"i": i, "start": t["start"], "end": t["end"], "midi": t["midi"],
                      "src_start": s["start"], "src_end": s["end"], "src_midi": s["midi"],
                      "shift_ms": 0, "semis": 0, "trim_start_ms": 0, "trim_end_ms": 0,
                      "mute": False})
    return items


def bend(vocal, items, total_len):
    out = np.zeros(total_len, dtype=np.float32)
    fade = int(0.006 * SR)
    for it in items:
        if it.get("mute"):
            continue
        a = int((it["src_start"] + it.get("trim_start_ms", 0) / 1000) * SR)
        b = int((it["src_end"] - it.get("trim_end_ms", 0) / 1000) * SR)
        if b - a < int(0.02 * SR):
            continue
        seg = vocal[a:b]
        want = (it["end"] - it["start"]) * SR
        if want < 0.02 * SR:
            continue
        rate = float(np.clip(len(seg) / want, 0.25, 4.0))
        steps = float(np.clip(it["midi"] - it["src_midi"] + it.get("semis", 0), -24, 24))
        piece = pyrb.time_stretch(seg, SR, rate, rbargs={"--pitch": "%.3f" % steps})
        piece = piece.astype(np.float32)
        f = min(fade, len(piece) // 2)
        if f > 0:
            ramp = np.linspace(0, 1, f, dtype=np.float32)
            piece[:f] *= ramp
            piece[-f:] *= ramp[::-1]
        p = int((it["start"] + it.get("shift_ms", 0) / 1000) * SR)
        if p < 0:
            piece, p = piece[-p:], 0
        end = min(total_len, p + len(piece))
        if end > p:
            out[p:end] += piece[:end - p]
    return out


def eleven(vocal_path, voice_id):
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key or not voice_id:
        return None
    with open(vocal_path, "rb") as fh:
        res = requests.post(
            "https://api.elevenlabs.io/v1/speech-to-speech/%s?output_format=mp3_44100_128" % voice_id,
            headers={"xi-api-key": key},
            files={"audio": ("vocal.wav", fh, "audio/wav")},
            data={"model_id": "eleven_multilingual_sts_v2"}, timeout=600)
    res.raise_for_status()
    return res.content


def render(job):
    d = job_dir(job)
    meta = json.load(open(os.path.join(d, "meta.json")))
    plan = json.load(open(os.path.join(d, "plan.json")))
    set_state(job, status="working", progress="bending")
    vocal, _ = librosa.load(os.path.join(meta["dir2"], "vocals.wav"), sr=SR, mono=True)
    inst, _ = librosa.load(os.path.join(meta["dir1"], "instrumental.wav"), sr=SR, mono=False)
    if inst.ndim == 1:
        inst = np.vstack([inst, inst])
    bent = bend(vocal, plan["items"], inst.shape[1])
    bent_path = os.path.join(d, "bent_vocal.wav")
    sf.write(bent_path, bent, SR)
    final = bent
    voice = meta.get("voice_id", "")
    if voice and os.environ.get("ELEVENLABS_API_KEY"):
        set_state(job, progress="singing with elevenlabs")
        audio = eleven(bent_path, voice)
        mp = os.path.join(d, "sung_vocal.mp3")
        open(mp, "wb").write(audio)
        sung, _ = librosa.load(mp, sr=SR, mono=True)
        final = np.zeros_like(bent)
        final[:min(len(sung), len(final))] = sung[:len(final)]
    set_state(job, progress="mixing")
    mix = inst * 0.8 + final[None, :] * 1.0
    peak = float(np.max(np.abs(mix))) or 1.0
    mix = mix / max(peak, 1.0) * 0.98
    wav = os.path.join(d, "mix.wav")
    sf.write(wav, mix.T, SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-b:a", "192k",
                    os.path.join(d, "mix.mp3")], check=True)
    os.remove(wav)
    rev = int(r.hget("sb:job:" + job, "rev") or 0) + 1
    set_state(job, status="done", progress="done", rev=rev)


def run_job(job):
    try:
        d = job_dir(job)
        meta = json.load(open(os.path.join(d, "meta.json")))
        set_state(job, status="working")
        dir1, t1 = fetch_and_split(meta["song1"], job, "song one")
        dir2, t2 = fetch_and_split(meta["song2"], job, "song two")
        meta.update({"dir1": dir1, "dir2": dir2, "title1": t1, "title2": t2})
        json.dump(meta, open(os.path.join(d, "meta.json"), "w"))
        set_state(job, title1=t1, title2=t2, progress="reading melody of song one")
        target = find_notes(os.path.join(dir1, "vocals.wav"))
        set_state(job, progress="reading syllables of song two")
        source = find_notes(os.path.join(dir2, "vocals.wav"))
        plan = {"items": build_plan(target, source)}
        json.dump(plan, open(os.path.join(d, "plan.json"), "w"))
        render(job)
    except Exception as e:
        set_state(job, status="error", progress="error", error=str(e)[:500])
        raise


def rerender(job):
    try:
        render(job)
    except Exception as e:
        set_state(job, status="error", progress="error", error=str(e)[:500])
        raise
