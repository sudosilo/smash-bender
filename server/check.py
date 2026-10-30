import os, sys, json, re, difflib, subprocess
import numpy as np

# usage: check.py JOB|last   (run with the WhisperX python)
# Listens to a finished job and reports how many intended words can be understood,
# and how much the mix sounds like each source track.
DATA = "/opt/smash-bender/data"
job = sys.argv[1]
if job == "last":
    job = open("/opt/smash-bender/last_job").read().strip()
d = os.path.join(DATA, "jobs", job)
meta = json.load(open(os.path.join(d, "meta.json")))
secs = float(meta.get("seconds") or 0) or 1e9


def norm(w):
    return re.sub(r"[^a-z0-9']", "", (w or "").lower())


intended = []
plan_path = os.path.join(d, "plan.json")
if os.path.exists(plan_path):
    for it in json.load(open(plan_path))["items"]:
        intended += [norm(w) for w in (it.get("word") or "").split()]
else:
    wp = os.path.join(meta["dir2"], "words.json")
    if os.path.exists(wp):
        intended = [norm(w["word"]) for w in json.load(open(wp))["words"] if w["start"] < secs]
intended = [w for w in intended if w]

import whisperx
audio = whisperx.load_audio(os.path.join(d, "mix.mp3"))
model = whisperx.load_model(os.environ.get("SB_WHISPER", "small"), "cpu", compute_type="int8", language="en")
heard_text = " ".join(s["text"].strip() for s in model.transcribe(audio, batch_size=4, language="en")["segments"])
heard = [norm(w) for w in heard_text.split() if norm(w)]
sm = difflib.SequenceMatcher(None, intended, heard, autojunk=False)
matched = sum(b.size for b in sm.get_matching_blocks())


def prints(path):
    if not os.path.exists(path):
        return None
    out = subprocess.run(["fpcalc", "-raw", "-length", "120", path], capture_output=True, text=True).stdout
    m = re.search(r"FINGERPRINT=([\d,]+)", out)
    return np.array([int(x) for x in m.group(1).split(",")], dtype=np.uint32) if m else None


def likeness(a, b):
    if a is None or b is None:
        return None
    best = 0.5
    for off in range(-40, 41):
        x = a[max(0, off):]
        y = b[max(0, -off):]
        n = min(len(x), len(y))
        if n < 20:
            continue
        diff = np.bitwise_xor(x[:n], y[:n])
        err = np.unpackbits(diff.view(np.uint8)).mean()
        best = min(best, err)
    return round(max(0.0, (0.5 - best) / 0.5) * 100, 1)


mix = prints(os.path.join(d, "mix.mp3"))
sources = {
    "song one full track": os.path.join(meta.get("dir1", ""), "song.wav"),
    "song one music": os.path.join(meta.get("dir1", ""), "instrumental.wav"),
    "song one voice": os.path.join(meta.get("dir1", ""), "vocals.wav"),
    "song two voice": os.path.join(meta.get("dir2", ""), "vocals.wav"),
}
sounds_like = {k: likeness(mix, prints(p)) for k, p in sources.items()}
sounds_like = {k: v for k, v in sounds_like.items() if v is not None}

report = {
    "job": job,
    "words_intended": len(intended),
    "words_understood": matched,
    "understood_pct": round(100.0 * matched / max(1, len(intended)), 1),
    "heard": heard_text[:400],
    "sounds_like_pct": sounds_like,
}
json.dump(report, open(os.path.join(d, "check.json"), "w"), indent=1)
print("words understood: %d of %d (%.1f%%)" % (matched, len(intended), report["understood_pct"]))
print("what it heard:", report["heard"])
for k, v in sounds_like.items():
    print("sounds like %s: %s%%" % (k, v))
