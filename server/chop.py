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


def mini(mel, dur, steps=32):
    step = dur / steps
    cells = [None] * steps
    for n in mel:
        a = int(round(n["start"] / step))
        b = max(a + 1, int(round(n["end"] / step)))
        if a >= steps:
            continue
        if cells[a] is None:
            cells[a] = (name(n["midi"]), min(b, steps) - a)
    out, i, rest = [], 0, 0
    while i < steps:
        c = cells[i]
        if c is None:
            rest += 1
            i += 1
            continue
        if rest:
            out.append("~" if rest == 1 else "~@%d" % rest)
            rest = 0
        length = c[1]
        nxt = next((j for j in range(i + 1, i + length) if cells[j] is not None), i + length)
        length = nxt - i
        out.append(c[0] if length == 1 else "%s@%d" % (c[0], length))
        i += length
    if rest:
        out.append("~" if rest == 1 else "~@%d" % rest)
    return " ".join(out)


mel = read_notes(wav) if os.environ.get("CHOP_FAKE") is None else json.loads(os.environ["CHOP_FAKE"])
if mel:
    w = np.array([n["end"] - n["start"] for n in mel])
    base = name(int(round(np.median(np.repeat([n["midi"] for n in mel], np.maximum(1, (w * 100).astype(int)))))))
else:
    base = "c3"
pattern = mini(mel, dur) if mel else "~"
url = public.rstrip("/") + "/slice.mp3"
code = "\n".join([
    "// Smash Bender chop: %.2f seconds, %d notes" % (dur, len(mel)),
    "samples({ voice: { '%s': '%s' } })" % (base, url),
    "setcps(%.4f)" % (1.0 / dur),
    "const melody = \"%s\"" % pattern,
    "stack(",
    "  note(melody).s(\"voice\").clip(1),",
    "  note(melody).s(\"piano\").gain(0.6)",
    ")",
])
link = "https://strudel.cc/#" + urllib.parse.quote(base64.b64encode(code.encode()).decode())
json.dump({"seconds": dur, "notes": mel, "base_note": base, "pattern": pattern, "code": code,
           "strudel": link, "audio": url}, open(os.path.join(out, "chop.json"), "w"))
print(json.dumps({"notes": len(mel), "strudel": link}))
