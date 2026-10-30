import os, re, json, time, glob, subprocess
import numpy as np
import soundfile as sf
import requests
import redis

# Stage two: take one stage-one sample's placed voice, refine it four ways with a tool
# (ElevenLabs for now), mix each over the same music, check it, and log it like stage one.
BASE = os.environ.get("SB_BASE", "/opt/smash-bender")
DATA = os.path.join(BASE, "data")
EXP = os.path.join(DATA, "experiments")
SR = 44100
r = redis.Redis(decode_responses=True)
TOOLS = {"elevenlabs": "ElevenLabs"}


def find_parent(key, run):
    name = key.split("|")[0]
    for fn in glob.glob(os.path.join(EXP, "*.jsonl")):
        if fn.endswith(".stage2.jsonl"):
            continue
        for line in open(fn):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            k = rec.get("experiment", "") + "|" + rec.get("batch", rec.get("time", "")[:16])
            if k == key and int(rec.get("run", 0)) == int(run):
                work = os.path.join(EXP, name)
                rec.setdefault("voice_path", os.path.join(work, "placed%d.wav" % int(run)))
                rec.setdefault("inst_path", os.path.join(work, "inst.wav"))
                rec.setdefault("acap_path", os.path.join(work, "acap.wav"))
                rec.setdefault("reference_path", os.path.join(work, "reference_words.json"))
                return rec
    raise RuntimeError("stage one sample not found")


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


def eleven_voices(key):
    res = requests.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key}, timeout=60)
    res.raise_for_status()
    return [(v["voice_id"], v.get("name", "")) for v in res.json().get("voices", [])]


def eleven_sing(key, voice_id, wav, settings, clean):
    with open(wav, "rb") as fh:
        res = requests.post(
            "https://api.elevenlabs.io/v1/speech-to-speech/%s?output_format=mp3_44100_128" % voice_id,
            headers={"xi-api-key": key}, files={"audio": ("voice.wav", fh, "audio/wav")},
            data={"model_id": "eleven_multilingual_sts_v2", "remove_background_noise": "true" if clean else "false",
                  "voice_settings": json.dumps(settings)}, timeout=600)
    if res.status_code != 200:
        raise RuntimeError("ElevenLabs %d: %s" % (res.status_code, res.text[:200]))
    return res.content


def to_wav(src, dest, channels):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", str(channels), "-ar", str(SR), dest], check=True)


def run_stage2(job_id, key, run, tool="elevenlabs"):
    state = "sb:stage2:" + job_id
    try:
        parent = find_parent(key, run)
        name = parent["experiment"]
        stamp = time.strftime("%m%d%H%M")
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        if not api_key:
            raise RuntimeError("no ElevenLabs key on the server")
        voices = eleven_voices(api_key)
        main = os.environ.get("ELEVENLABS_VOICE_ID") or (voices[0][0] if voices else "")
        names = dict(voices)
        other = next((v for v, _ in voices if v != main), main)
        variants = [
            {"label": "plain", "hypothesis": "ElevenLabs smooths the chopped voice into one clean voice.",
             "voice": main, "settings": {"stability": 0.5, "similarity_boost": 0.75}, "clean": False},
            {"label": "noise removed", "hypothesis": "Removing leftover noise first makes the words clearer.",
             "voice": main, "settings": {"stability": 0.5, "similarity_boost": 0.75}, "clean": True},
            {"label": "loose and expressive", "hypothesis": "Lower stability lets the voice move more, like singing.",
             "voice": main, "settings": {"stability": 0.2, "similarity_boost": 0.6, "style": 0.4}, "clean": True},
            {"label": "second voice", "hypothesis": "A different voice may suit this melody better.",
             "voice": other, "settings": {"stability": 0.5, "similarity_boost": 0.75}, "clean": True},
        ]
        inst, _ = sf.read(parent["inst_path"])
        if inst.ndim == 1:
            inst = np.stack([inst, inst], 1)
        fp_inst = prints(parent["inst_path"])
        log = os.path.join(EXP, name + ".stage2.jsonl")
        for i, v in enumerate(variants, 1):
            r.hset(state, mapping={"status": "working", "progress": "sample %s of 4" % "ABCD"[i - 1]})
            folder = "%ss2%s%d" % (name, stamp, i)
            out = os.path.join(DATA, "jobs", folder)
            os.makedirs(out, exist_ok=True)
            sung_mp3 = os.path.join(out, "sung_vocal.mp3")
            open(sung_mp3, "wb").write(eleven_sing(api_key, v["voice"], parent["voice_path"], v["settings"], v["clean"]))
            sung_wav = os.path.join(out, "sung.wav")
            to_wav(sung_mp3, sung_wav, 1)
            y, _ = sf.read(sung_wav)
            vv = np.zeros(len(inst))
            vv[:min(len(y), len(vv))] = y[:len(vv)]
            sf.write(sung_wav, vv, SR)
            il = float(np.sqrt(np.mean(inst ** 2))) or 1e-3
            loud = vv[np.abs(vv) > 1e-4]
            vl = float(np.sqrt(np.mean(loud ** 2))) if len(loud) else 1e-3
            mix = inst + (vv * il * 1.4 / vl)[:, None]
            mix /= max(1.0, float(np.max(np.abs(mix)))) / 0.98
            tmp = os.path.join(out, "mix.wav")
            sf.write(tmp, mix, SR)
            mp3 = os.path.join(out, "mix.mp3")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-b:a", "192k", mp3], check=True)
            os.remove(tmp)
            heard = json.loads(subprocess.run(
                [BASE + "/wx/bin/python", BASE + "/repo/server/listen.py", parent["acap_path"], mp3, parent["reference_path"]],
                capture_output=True, text=True).stdout.strip().splitlines()[-1])
            fp_mix = prints(mp3)
            music_like, voice_like = likeness(fp_mix, fp_inst), likeness(fp_mix, prints(sung_wav))
            both = min(music_like or 0, voice_like or 0)
            notes = ["Words come through clearly." if heard["understood_pct"] >= 70 else
                     "Most words come through." if heard["understood_pct"] >= 40 else "Words are hard to make out.",
                     "The music is easy to recognize." if (music_like or 0) >= 30 else "The music is getting buried.",
                     "The singer is easy to recognize." if (voice_like or 0) >= 30 else "The singer is getting buried.",
                     "Voice used: %s." % (names.get(v["voice"]) or "account voice")]
            rec = {"time": time.strftime("%Y-%m-%d %H:%M"), "batch": stamp, "experiment": name, "stage": tool,
                   "stage_name": TOOLS.get(tool, tool), "run": i, "sample": "ABCD"[i - 1], "label": v["label"],
                   "hypothesis": v["hypothesis"], "parent_key": key, "parent_run": int(run),
                   "parent_sample": parent.get("sample", "ABCD"[int(run) - 1]), "parent_label": parent.get("label", ""),
                   "parent_time": parent.get("time", ""), "song_one": parent.get("song_one", ""),
                   "song_two": parent.get("song_two", ""), "words_understood_pct": heard["understood_pct"],
                   "sounds_like_music_pct": music_like, "sounds_like_voice_pct": voice_like,
                   "both_recognizable_pct": both, "notes": " ".join(notes), "heard": heard["heard"],
                   "audio": "/files/%s/mix.mp3" % folder}
            open(log, "a").write(json.dumps(rec) + "\n")
        r.hset(state, mapping={"status": "done", "progress": "done"})
    except Exception as e:
        r.hset(state, mapping={"status": "error", "progress": "error", "error": str(e)[:300]})
        raise
