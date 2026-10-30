import sys
import numpy as np
import soundfile as sf
import pyworld as pw

# usage: autotune.py IN_WAV OUT_WAV KEY SCALE SPEED_MS [chromatic]   (lab python)
# Pulls each moment of the voice to the nearest note in KEY SCALE (or any half step with chromatic).
# SPEED_MS is how long the pull takes: 0 is the instant robotic sound, 100 or more is gentle correction.
src, dest, key, scale, speed = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5])
chromatic = len(sys.argv) > 6 and sys.argv[6] == "chromatic"
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
root = NOTES.index(FLATS.get(key, key)) if FLATS.get(key, key) in NOTES else 0
steps = [0, 2, 3, 5, 7, 8, 10] if scale == "minor" else [0, 2, 4, 5, 7, 9, 11]
allowed = np.array(range(12)) if chromatic else np.array([(root + s) % 12 for s in steps])

x, sr = sf.read(src)
if x.ndim > 1:
    x = x.mean(1)
x = np.ascontiguousarray(x, dtype=np.float64)
period = 5.0
f0, t = pw.dio(x, sr, f0_floor=65.0, f0_ceil=1000.0, frame_period=period)
f0 = pw.stonemask(x, f0, t, sr)
sp = pw.cheaptrick(x, f0, t, sr)
ap = pw.d4c(x, f0, t, sr)

voiced = f0 > 0
midi = np.zeros_like(f0)
midi[voiced] = 69 + 12 * np.log2(f0[voiced] / 440.0)
target = midi.copy()
for i in np.where(voiced)[0]:
    base = np.floor(midi[i] / 12) * 12
    cands = np.concatenate([base - 12 + allowed, base + allowed, base + 12 + allowed])
    target[i] = cands[np.argmin(np.abs(cands - midi[i]))]
corr = np.where(voiced, target - midi, 0.0)
if speed > 0:
    a = np.exp(-period / speed)
    smooth = np.zeros_like(corr)
    for i in range(len(corr)):
        if not voiced[i]:
            smooth[i] = 0.0
        elif i > 0 and voiced[i - 1]:
            smooth[i] = a * smooth[i - 1] + (1 - a) * corr[i]
        else:
            smooth[i] = corr[i]
    corr = smooth
new_f0 = np.where(voiced, f0 * 2 ** (corr / 12.0), 0.0)
y = pw.synthesize(new_f0, sp, ap, sr, period)
y = y[:len(x)] if len(y) >= len(x) else np.concatenate([y, np.zeros(len(x) - len(y))])
peak = float(np.max(np.abs(y))) or 1.0
sf.write(dest, y / max(peak, 1.0) * 0.98, sr)
print("tuned %.0f%% of the voice frames" % (100.0 * voiced.mean()))
