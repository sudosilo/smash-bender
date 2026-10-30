import os, sys, json, re, subprocess, time
import numpy as np
import soundfile as sf
import essentia.standard as es

# usage: experiment.py INSTRUMENTAL_FILE ACAPELLA_FILE NAME [SECONDS] [MAX_RUNS]   (lab python)
# Runs up to MAX_RUNS (cap 4) versions of song two's a cappella over song one's instrumental,
# each testing one idea, checks every result, and logs hypothesis, change, measurements and notes.
BASE = "/opt/smash-bender"
INBOX = BASE + "/data/inbox"
inst_file, acap_file, name = sys.argv[1], sys.argv[2], sys.argv[3]
secs = float(sys.argv[4]) if len(sys.argv) > 4 else 45.0
runs = min(4, int(sys.argv[5]) if len(sys.argv) > 5 else 4)
SR = 44100
work = os.path.join(BASE, "data", "experiments", name)
os.makedirs(work, exist_ok=True)
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def ff(src, dest, extra=()):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-t", str(secs), "-ar", str(SR)] + list(extra) + [dest], check=True)


inst_wav, acap_wav = os.path.join(work, "inst.wav"), os.path.join(work, "acap.wav")
ff(os.path.join(INBOX, inst_file), inst_wav, ["-ac", "2"])
ff(os.path.join(INBOX, acap_file), acap_wav, ["-ac", "1"])


def analyze(path):
    mono = es.MonoLoader(filename=path, sampleRate=SR)()
    key, scale, strength = es.KeyExtractor()(mono)
    bpm, beats, _, _, _ = es.RhythmExtractor2013(method="multifeature")(mono)
    return {"key": key, "scale": scale, "key_strength": round(float(strength), 2),
            "bpm": round(float(bpm), 1), "beats": [float(b) for b in beats]}


def pitch_class(key, scale):
    pc = NOTES.index(key) if key in NOTES else {"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10}.get(key, 0)
    return (pc + 3) % 12 if scale == "minor" else pc


A_inst, A_acap = analyze(inst_wav), analyze(acap_wav)
semis = (pitch_class(A_inst["key"], A_inst["scale"]) - pitch_class(A_acap["key"], A_acap["scale"])) % 12
semis = semis - 12 if semis > 6 else semis
ratio = A_acap["bpm"] / A_inst["bpm"] if A_inst["bpm"] and A_acap["bpm"] else 1.0
while ratio > 1.33:
    ratio /= 2
while ratio < 0.75:
    ratio *= 2
period = 60.0 / A_inst["bpm"] if A_inst["bpm"] else 0.5


def first_voice(path):
    y, _ = sf.read(path)
    env = np.abs(y if y.ndim == 1 else y.mean(1))
    win = int(0.02 * SR)
    lvl = np.convolve(env, np.ones(win) / win, mode="same")
    idx = np.where(lvl > 0.1 * lvl.max())[0]
    return idx[0] / SR if len(idx) else 0.0


VARIANTS = [
    {"label": "baseline", "hypothesis": "Control run: a cappella laid over the music untouched.",
     "key": False, "tempo": False, "align": False},
    {"label": "key matched", "hypothesis": "Moving the voice into the music's key makes both sound like one song.",
     "key": True, "tempo": False, "align": False},
    {"label": "tempo matched", "hypothesis": "Stretching the voice to the music's tempo keeps words on the beat.",
     "key": False, "tempo": True, "align": True},
    {"label": "key and tempo", "hypothesis": "Key and tempo together beat either change alone.",
     "key": True, "tempo": True, "align": True},
][:runs]


def prints(path):
    out = subprocess.run(["fpcalc", "-raw", "-length", "120", path], capture_output=True, text=True).stdout
    m = re.search(r"FINGERPRINT=([\d,]+)", out)
    return np.array([int(x) for x in m.group(1).split(",")], dtype=np.uint32) if m else None


def likeness(a, b):
    if a is None or b is None:
        return None
    best = 0.5
    for off in range(-40, 41):
        x, y = a[max(0, off):], b[max(0, -off):]
        n = min(len(x), len(y))
        if n >= 20:
            best = min(best, np.unpackbits(np.bitwise_xor(x[:n], y[:n]).view(np.uint8)).mean())
    return round(max(0.0, (0.5 - best) / 0.5) * 100, 1)


fp_inst = prints(inst_wav)
inst, _ = sf.read(inst_wav)
log_path = os.path.join(BASE, "data", "experiments", name + ".jsonl")
results = []
print("music: key %s %s, %.1f BPM | voice: key %s %s, %.1f BPM" % (
    A_inst["key"], A_inst["scale"], A_inst["bpm"], A_acap["key"], A_acap["scale"], A_acap["bpm"]))
for i, v in enumerate(VARIANTS, 1):
    voice = os.path.join(work, "voice%d.wav" % i)
    args = ["rubberband", "-q", "--formant"]
    if v["key"]:
        args += ["-p", str(semis)]
    if v["tempo"]:
        args += ["-t", "%.5f" % ratio]
    if v["key"] or v["tempo"]:
        subprocess.run(args + [acap_wav, voice], check=True, capture_output=True)
    else:
        subprocess.run(["cp", acap_wav, voice], check=True)
    y, _ = sf.read(voice)
    if y.ndim > 1:
        y = y.mean(1)
    shift = 0.0
    if v["align"] and A_inst["beats"]:
        start = first_voice(voice)
        target = min(A_inst["beats"], key=lambda b: abs(b - start))
        shift = target - start
        n = int(abs(shift) * SR)
        y = np.concatenate([np.zeros(n), y]) if shift > 0 else y[n:]
    vv = np.zeros(len(inst))
    vv[:min(len(y), len(vv))] = y[:len(vv)]
    placed = os.path.join(work, "placed%d.wav" % i)
    sf.write(placed, vv, SR)
    il = float(np.sqrt(np.mean(inst ** 2))) or 1e-3
    loud = vv[np.abs(vv) > 1e-4]
    vl = float(np.sqrt(np.mean(loud ** 2))) if len(loud) else 1e-3
    mix = inst + (vv * il * 1.4 / vl)[:, None]
    mix /= max(1.0, float(np.max(np.abs(mix)))) / 0.98
    out_dir = os.path.join(BASE, "data", "jobs", "%s%d" % (name, i))
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, "mix.wav")
    sf.write(tmp, mix, SR)
    mp3 = os.path.join(out_dir, "mix.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-b:a", "192k", mp3], check=True)
    os.remove(tmp)
    heard = json.loads(subprocess.run([BASE + "/wx/bin/python", BASE + "/repo/server/listen.py", acap_wav, mp3,
                                       os.path.join(work, "reference_words.json")],
                                      capture_output=True, text=True).stdout.strip().splitlines()[-1])
    fp_mix = prints(mp3)
    music_like, voice_like = likeness(fp_mix, fp_inst), likeness(fp_mix, prints(placed))
    both = min(music_like or 0, voice_like or 0)
    notes = []
    notes.append("Words come through clearly." if heard["understood_pct"] >= 70 else
                 "Most words come through." if heard["understood_pct"] >= 40 else
                 "Words are hard to make out.")
    notes.append("The music is easy to recognize." if (music_like or 0) >= 30 else "The music is getting buried.")
    notes.append("The singer is easy to recognize." if (voice_like or 0) >= 30 else "The singer is getting buried.")
    if v["key"]:
        notes.append("Voice moved %+d half steps toward %s %s." % (semis, A_inst["key"], A_inst["scale"]))
    if v["tempo"]:
        notes.append("Voice stretched to %.0f%% of its length to match %.0f BPM." % (ratio * 100, A_inst["bpm"]))
    if v["align"]:
        notes.append("First word moved %+.2f seconds onto a beat." % shift)
    rec = {"time": time.strftime("%Y-%m-%d %H:%M"), "experiment": name, "run": i, "label": v["label"],
           "hypothesis": v["hypothesis"], "words_understood_pct": heard["understood_pct"],
           "sounds_like_music_pct": music_like, "sounds_like_voice_pct": voice_like,
           "both_recognizable_pct": both, "notes": " ".join(notes), "heard": heard["heard"],
           "listen": "smash-bender.167-233-137-169.sslip.io/files/%s%d/mix.mp3" % (name, i)}
    results.append(rec)
    open(log_path, "a").write(json.dumps(rec) + "\n")
    print("\nRUN %d %s | words %.1f%% | music %s%% | voice %s%% | both %s%%" % (
        i, v["label"], heard["understood_pct"], music_like, voice_like, both))
    print("  idea: " + v["hypothesis"])
    print("  notes: " + rec["notes"])
    print("  LISTEN " + rec["listen"])

best = max(results, key=lambda r: (r["both_recognizable_pct"], r["words_understood_pct"]))
print("\nBEST: run %d (%s). Log saved in data/experiments/%s.jsonl" % (best["run"], best["label"], name))
