import os, sys, json, subprocess
import numpy as np
import soundfile as sf

# usage: instrument.py VOICE_WAV OUT_WAV PROGRAM NOTES_CACHE_JSON   (Basic Pitch python)
# Reads the voice's melody as notes (cached per voice), then plays those notes on a General MIDI
# instrument (PROGRAM: 0 piano, 48 strings, 56 trumpet, 81 synth lead), as hard as each note was sung.
src, dest, program, cache = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
voice, sr = sf.read(src)
if voice.ndim > 1:
    voice = voice.mean(1)

if os.path.exists(cache):
    melody = json.load(open(cache))
else:
    from basic_pitch.inference import predict
    _, _, events = predict(src)
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
        melody.append({"start": start, "end": end, "midi": pitch, "amp": amp})
    json.dump(melody, open(cache, "w"))

import pretty_midi
levels = []
for n in melody:
    seg = voice[int(n["start"] * sr):max(int(n["start"] * sr) + 1, int(n["end"] * sr))]
    levels.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
lo, hi = (np.percentile(levels, 5), np.percentile(levels, 95)) if levels else (0, 1)
pm = pretty_midi.PrettyMIDI()
track = pretty_midi.Instrument(program=program)
for i, n in enumerate(melody):
    loud = float(np.clip((levels[i] - lo) / (hi - lo), 0, 1)) if hi > lo else 0.7
    track.notes.append(pretty_midi.Note(velocity=int(35 + 92 * loud ** 0.7), pitch=int(n["midi"]),
                                        start=n["start"], end=n["end"]))
pm.instruments.append(track)
mid = dest + ".mid"
pm.write(mid)
tmp = dest + ".fs.wav"
subprocess.run(["fluidsynth", "-ni", "-g", "1.0", "-r", str(sr), "-F", tmp,
                "/usr/share/sounds/sf2/FluidR3_GM.sf2", mid], check=True, capture_output=True)
y, _ = sf.read(tmp)
if y.ndim > 1:
    y = y.mean(1)
out = np.zeros(len(voice))
out[:min(len(y), len(out))] = y[:len(out)]
sf.write(dest, out, sr)
os.remove(tmp)
os.remove(mid)
print("played %d notes" % len(melody))
