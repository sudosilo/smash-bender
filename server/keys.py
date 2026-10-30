import os, sys, json, subprocess
import numpy as np
import soundfile as sf
import pretty_midi

# usage: keys.py MELODY_NAME INSTRUMENTAL_FILE OUTPUT_NAME [PROGRAM] [SECONDS]
# MELODY_NAME is a folder made by bpmelody.py; PROGRAM is a General MIDI number (0 = piano)
base = "/opt/smash-bender/data"
notes = json.load(open(os.path.join(base, "jobs", sys.argv[1], "notes.json")))["melody"]
inst_src = os.path.join(base, "inbox", sys.argv[2])
out = os.path.join(base, "jobs", sys.argv[3])
program = int(sys.argv[4]) if len(sys.argv) > 4 else 0
secs = sys.argv[5] if len(sys.argv) > 5 else "45"
os.makedirs(out, exist_ok=True)
SR = 44100

pm = pretty_midi.PrettyMIDI()
track = pretty_midi.Instrument(program=program)
for n in notes:
    vel = int(np.clip(50 + 77 * n.get("amp", 0.7), 40, 127))
    track.notes.append(pretty_midi.Note(velocity=vel, pitch=int(n["midi"]), start=n["start"], end=n["end"]))
pm.instruments.append(track)
mid = os.path.join(out, "melody.mid")
pm.write(mid)

font = "/usr/share/sounds/sf2/FluidR3_GM.sf2"
keys_wav = os.path.join(out, "keys.wav")
subprocess.run(["fluidsynth", "-ni", "-g", "1.0", "-r", str(SR), "-F", keys_wav, font, mid],
               check=True, capture_output=True)
inst_wav = os.path.join(out, "instrumental.wav")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", inst_src, "-t", secs, "-ac", "2", "-ar", str(SR), inst_wav], check=True)

inst, _ = sf.read(inst_wav)
keys, _ = sf.read(keys_wav)
if keys.ndim == 1:
    keys = np.stack([keys, keys], 1)
n = len(inst)
k = np.zeros_like(inst)
k[:min(n, len(keys))] = keys[:n]
il = float(np.sqrt(np.mean(inst ** 2))) or 1e-3
loud = k[np.abs(k).max(1) > 1e-4]
kl = float(np.sqrt(np.mean(loud ** 2))) if len(loud) else 0.0
if kl > 1e-5:
    k *= il * 1.2 / kl
mix = inst + k
mix /= max(1.0, float(np.max(np.abs(mix)))) / 0.98
for data, fname in ((k, "bent_vocal"), (mix, "mix")):
    tmp = os.path.join(out, fname + ".wav")
    sf.write(tmp, data, SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-b:a", "192k",
                    os.path.join(out, fname + ".mp3")], check=True)
    os.remove(tmp)
os.remove(keys_wav)
os.remove(inst_wav)
print("KEYS ALONE smash-bender.167-233-137-169.sslip.io/files/%s/bent_vocal.mp3" % sys.argv[3])
print("KEYS OVER MUSIC smash-bender.167-233-137-169.sslip.io/files/%s/mix.mp3" % sys.argv[3])
