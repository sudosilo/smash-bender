import os, sys, json, base64, subprocess, urllib.parse
import numpy as np

# usage: chop.py SOURCE_AUDIO START END OUT_DIR PUBLIC_BASE   (Basic Pitch python)
# Cuts START..END seconds out of SOURCE_AUDIO, reads that slice's melody as notes, and writes:
#   slice.mp3     the cut, for playback and as a playable sample
#   chop.json     notes, the Strudel code and a ready strudel.cc link
src, start, end, out, public = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4], sys.argv[5]
dur = round(end - start, 3)
if dur < 0.3 or dur > 30:
    sys.exit("pick a slice between 0.3 and 30 seconds long")
os.makedirs(out, exist_ok=True)
wav, mp3 = os.path.join(out, "slice.wav"), os.path.join(out, "slice.mp3")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.3f" % start, "-t", "%.3f" % dur, "-i", src,
                "-ac", "1", "-ar", "44100", "-af", "afade=t=in:d=0.01,areverse,afade=t=in:d=0.02,areverse", wav],
               check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-b:a", "192k", mp3], check=True)

NAMES = ["c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b"]


def name(m):
    return "%s%d" % (NAMES[int(m) % 12], int(m) // 12 - 1)


def read_notes(path):
    from basic_pitch.inference import predict
    _, _, events = predict(path)
    events = sorted(events, key=lambda e: (e[0], -e[3]))
    mel = []
    for e in events:
        s, t, p, a = float(e[0]), float(e[1]), int(e[2]), float(e[3])
        if mel and s < mel[-1]["end"]:
            if a > mel[-1]["amp"]:
                mel[-1]["end"] = s
                if mel[-1]["end"] - mel[-1]["start"] < 0.05:
                    mel.pop()
            else:
                continue
        mel.append({"start": round(s, 3), "end": round(t, 3), "midi": p, "amp": round(a, 3)})
    return mel


def clean(mel):
    mel = [dict(n) for n in mel if n["end"] - n["start"] >= 0.07]
    for i in range(len(mel)):
        nb = [mel[j]["midi"] for j in (i - 1, i + 1) if 0 <= j < len(mel)]
        if nb:
            ref = sum(nb) / len(nb)
            for shift in (-12, 12):
                if abs(mel[i]["midi"] + shift - ref) < abs(mel[i]["midi"] - ref) - 6:
                    mel[i]["midi"] += shift
    out = []
    for n in mel:
        if out and n["midi"] == out[-1]["midi"] and n["start"] - out[-1]["end"] < 0.08:
            out[-1]["end"] = n["end"]
            continue
        out.append(n)
    return out


def timed(mel, dur, value):
    """Mini-notation with each event weighted by its length in hundredths of a second, so timing is exact."""
    unit, parts, t = 0.01, [], 0.0
    for n in mel:
        gap = int(round((n["start"] - t) / unit))
        if gap > 0:
            parts.append("~@%d" % gap)
        length = max(1, int(round((n["end"] - max(n["start"], t)) / unit)))
        parts.append("%s@%d" % (value(n), length))
        t = max(t, n["start"]) + length * unit
    tail = int(round((dur - t) / unit))
    if tail > 0:
        parts.append("~@%d" % tail)
    return " ".join(parts) or "~"


mel = read_notes(wav) if os.environ.get("CHOP_FAKE") is None else json.loads(os.environ["CHOP_FAKE"])
mel = clean(mel)
if mel:
    w = np.array([n["end"] - n["start"] for n in mel])
    base = name(int(round(np.median(np.repeat([n["midi"] for n in mel], np.maximum(1, (w * 100).astype(int)))))))
else:
    base = "c3"
pattern = timed(mel, dur, lambda n: name(n["midi"])) if mel else "~"
starts = timed(mel, dur, lambda n: "%.3f" % (n["start"] / dur)) if mel else "~"
url = public.rstrip("/") + "/slice.mp3"
code = "\n".join([
    "// Smash Bender chop: %.2f seconds, %d notes, timed to the hundredth of a second" % (dur, len(mel)),
    "samples({ voice: { '%s': '%s' } })" % (base, url),
    "setcps(%.4f) // one loop = the slice's own length" % (1.0 / dur),
    "const melody = \"%s\"" % pattern,
    "const starts = \"%s\"" % starts,
    "stack(",
    "  s(\"voice\").clip(1),                    // the slice itself, once per loop",
    "  note(melody).s(\"piano\").gain(0.7),     // the notes it heard, in time with it",
    "  // note(melody).s(\"voice\").begin(starts).clip(1),  // remove the // to play each note from its own spot in the voice",
    ")",
])
link = "https://strudel.cc/#" + urllib.parse.quote(base64.b64encode(code.encode()).decode())
json.dump({"seconds": dur, "notes": mel, "base_note": base, "pattern": pattern, "code": code,
           "strudel": link, "audio": url}, open(os.path.join(out, "chop.json"), "w"))
print(json.dumps({"notes": len(mel), "strudel": link}))
