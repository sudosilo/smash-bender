import os, sys, json, subprocess
import numpy as np
import soundfile as sf
from basic_pitch.inference import predict

# usage: bpmelody.py INBOX_FILE OUTPUT_NAME [SECONDS]
src = os.path.join("/opt/smash-bender/data/inbox", sys.argv[1])
name = sys.argv[2]
secs = sys.argv[3] if len(sys.argv) > 3 else "45"
out = os.path.join("/opt/smash-bender/data/jobs", name)
os.makedirs(out, exist_ok=True)
wav = os.path.join(out, "acapella.wav")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-t", secs, "-ac", "1", "-ar", "44100", wav], check=True)

_, _, events = predict(wav)
events = sorted(events, key=lambda e: (e[0], -e[3]))
melody = []
for e in events:
    start, end, pitch, amp = float(e[0]), float(e[1]), int(e[2]), float(e[3])
    if melody and start < melody[-1]["end"]:
        if amp > melody[-1]["amp"]:
            melody[-1]["end"] = start
            if melody[-1]["end"] - melody[-1]["start"] < 0.05:
                melody.pop()
        else:
            continue
    melody.append({"start": round(start, 3), "end": round(end, 3), "midi": pitch, "amp": round(amp, 3)})
json.dump({"all_notes": len(events), "melody": melody}, open(os.path.join(out, "notes.json"), "w"))

voice, sr = sf.read(wav)
tones = np.zeros(len(voice))
for n in melody:
    a, b = int(n["start"] * sr), min(len(tones), int(n["end"] * sr))
    if b <= a:
        continue
    t = np.arange(b - a) / sr
    f = 440.0 * 2 ** ((n["midi"] - 69) / 12.0)
    env = np.minimum(1, np.minimum(t / 0.01, (t[-1] - t) / 0.02 + 1e-9))
    tones[a:b] += 0.25 * env * (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t))
both = 0.6 * voice / (np.max(np.abs(voice)) or 1) + tones
both /= max(1.0, np.max(np.abs(both)))
for data, fname in ((tones, "bent_vocal"), (both, "mix")):
    tmp = os.path.join(out, fname + ".wav")
    sf.write(tmp, data, sr)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-b:a", "192k",
                    os.path.join(out, fname + ".mp3")], check=True)
    os.remove(tmp)

names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
print("notes found:", len(events), "| melody notes kept:", len(melody))
print("first notes:", " ".join("%s%d" % (names[n["midi"] % 12], n["midi"] // 12 - 1) for n in melody[:16]))
print("MELODY TONES smash-bender.167-233-137-169.sslip.io/files/%s/bent_vocal.mp3" % name)
print("TONES WITH VOICE smash-bender.167-233-137-169.sslip.io/files/%s/mix.mp3" % name)
