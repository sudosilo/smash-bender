import os, sys, json, re
import numpy as np
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import pipeline as p

# usage: score.py JOB|last SONG1_ARTIST SONG1_TRACK
job = sys.argv[1]
if job == "last":
    job = open("/opt/smash-bender/last_job").read().strip()
artist, track = sys.argv[2], sys.argv[3]
d = os.path.join(p.DATA, "jobs", job)
meta = json.load(open(os.path.join(d, "meta.json")))
plan = json.load(open(os.path.join(d, "plan.json")))
dir1 = meta["dir1"]

lyr = p.fetch_lyrics(dir1, {"artist": artist, "track": track}, job, "song one")
words1 = p.word_map(dir1, job, "song one", lyr)


def norm(w):
    return re.sub(r"[^a-z']", "", w.lower())


placed = []
for it in plan["items"]:
    for k, w in enumerate((it.get("word") or "").split()):
        placed.append((norm(w), it["start"] if k == 0 else None))
n = min(len(placed), len(words1))
same = sum(1 for i in range(n) if placed[i][0] and placed[i][0] == norm(words1[i]["word"]))
gaps = [abs(placed[i][1] - words1[i]["start"]) * 1000 for i in range(n)
        if placed[i][1] is not None and placed[i][0] == norm(words1[i]["word"])]

ta = p.pitch_track(os.path.join(dir1, "vocals.wav"))
tb = p.pitch_track(os.path.join(d, "bent_vocal.wav"))
m = min(len(ta), len(tb))
both = ~np.isnan(ta[:m]) & ~np.isnan(tb[:m])
cents = np.abs(tb[:m][both] - ta[:m][both]) * 100
sung_a = int((~np.isnan(ta[:m])).sum())

score = {
    "job": job,
    "words_singer_a": len(words1), "words_placed": len(placed),
    "words_in_same_order_pct": round(100.0 * same / max(1, len(words1)), 1),
    "word_start_error_ms_median": round(float(np.median(gaps)), 0) if gaps else None,
    "word_starts_within_100ms_pct": round(100.0 * sum(g <= 100 for g in gaps) / max(1, len(gaps)), 1) if gaps else None,
    "pitch_error_cents_median": round(float(np.median(cents)), 0) if len(cents) else None,
    "pitch_within_50_cents_pct": round(100.0 * float((cents <= 50).mean()), 1) if len(cents) else None,
    "melody_covered_pct": round(100.0 * int(both.sum()) / max(1, sung_a), 1),
}
json.dump(score, open(os.path.join(d, "score.json"), "w"), indent=1)
for k, v in score.items():
    print("%s: %s" % (k, v))
