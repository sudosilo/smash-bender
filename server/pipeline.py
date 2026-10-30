import os, re, json, hashlib, shutil, subprocess
import numpy as np
import soundfile as sf
import librosa
import pyrubberband as pyrb
import requests
import redis

DATA = os.environ.get("SB_DATA", "/opt/smash-bender/data")
PY = os.environ.get("SB_PY", "/opt/smash-bender/venv/bin/python")
SR = 44100
ASR = 22050
HOP = 256
r = redis.Redis(decode_responses=True)


def set_state(job, **kw):
    r.hset("sb:job:" + job, mapping={k: str(v) for k, v in kw.items()})


def job_dir(job):
    d = os.path.join(DATA, "jobs", job)
    os.makedirs(d, exist_ok=True)
    return d


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = (p.stderr or p.stdout or "").strip().splitlines()[-4:]
        raise RuntimeError(os.path.basename(cmd[2] if len(cmd) > 2 else cmd[0]) + ": " + " | ".join(tail))
    return p


def song_key(q):
    return hashlib.sha1(q.strip().lower().encode()).hexdigest()[:16]


BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
           "Accept": "audio/*,*/*;q=0.8", "Referer": "https://ccmixter.org/"}


def grab(url, dest, seconds=0):
    tmp = dest + ".dl"
    with requests.get(url, headers=BROWSER, stream=True, timeout=120) as res:
        res.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in res.iter_content(1 << 16):
                fh.write(chunk)
    trim(tmp, dest, seconds)
    os.remove(tmp)


def trim(src, dest, seconds=0):
    cut = ["-t", str(seconds)] if seconds and seconds > 0 else []
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src] + cut + ["-ar", str(SR), dest])


def demucs(d, src, job, label):
    voc = os.path.join(d, "vocals.wav")
    inst = os.path.join(d, "instrumental.wav")
    if os.path.exists(voc) and os.path.exists(inst):
        return
    set_state(job, progress="splitting " + label)
    out = os.path.join(d, "sep")
    run([PY, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs",
         "--segment", "7", "-j", "1", "-o", out, src])
    shutil.move(os.path.join(out, "htdemucs", "song", "vocals.wav"), voc)
    shutil.move(os.path.join(out, "htdemucs", "song", "no_vocals.wav"), inst)
    shutil.rmtree(out, ignore_errors=True)


def fetch_and_split(spec, job, label, need_inst, seconds=0):
    if isinstance(spec, dict):
        return fetch_urls(spec, job, label, need_inst, seconds)
    query = spec
    d = os.path.join(DATA, "songs", song_key(query + "|" + str(seconds)))
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, "song.wav")
    if not os.path.exists(src):
        set_state(job, progress="downloading " + label)
        target = query if query.startswith("http") else "ytsearch1:" + query
        cmd = [PY, "-m", "yt_dlp", "--no-playlist", "-x", "--audio-format", "wav",
               "--print-to-file", "%(title)s", os.path.join(d, "title.txt"),
               "-o", os.path.join(d, "full.%(ext)s")]
        cookies = os.path.join(os.path.dirname(DATA), "cookies.txt")
        if os.path.exists(cookies):
            cmd += ["--cookies", cookies]
        run(cmd + [target])
        full = os.path.join(d, "full.wav")
        trim(full, src, seconds)
        os.remove(full)
    demucs(d, src, job, label)
    title = ""
    tp = os.path.join(d, "title.txt")
    if os.path.exists(tp):
        lines = open(tp).read().strip().splitlines()
        title = lines[0] if lines else ""
    return d, title


def fetch_urls(spec, job, label, need_inst, seconds=0):
    key = json.dumps(spec, sort_keys=True) + "|" + str(seconds)
    d = os.path.join(DATA, "songs", song_key(key))
    os.makedirs(d, exist_ok=True)
    voc = os.path.join(d, "vocals.wav")
    inst = os.path.join(d, "instrumental.wav")
    set_state(job, progress="downloading " + label)
    if spec.get("file") or spec.get("url"):
        src = os.path.join(d, "song.wav")
        if not os.path.exists(src):
            if spec.get("file"):
                trim(spec["file"], src, seconds)
            else:
                grab(spec["url"], src, seconds)
        demucs(d, src, job, label)
    else:
        if spec.get("vocals_url") and not os.path.exists(voc):
            grab(spec["vocals_url"], voc, seconds)
        if spec.get("instrumental_url") and not os.path.exists(inst):
            grab(spec["instrumental_url"], inst, seconds)
    if not os.path.exists(voc) or (need_inst and not os.path.exists(inst)):
        raise RuntimeError(label + ": missing vocals or instrumental source")
    return d, spec.get("title", "")


WX = os.environ.get("SB_WX", "/opt/smash-bender/wx/bin/python")


def fetch_lyrics(d, spec, job, label):
    path = os.path.join(d, "lyrics.json")
    if os.path.exists(path):
        return path
    if not isinstance(spec, dict) or not spec.get("track"):
        return ""
    set_state(job, progress="getting lyrics for " + label)
    try:
        res = requests.get("https://lrclib.net/api/get", timeout=30,
                           params={"artist_name": spec.get("artist", ""), "track_name": spec["track"]},
                           headers={"User-Agent": "smash-bender/1.0"})
        synced = res.json().get("syncedLyrics") if res.ok else None
    except (requests.RequestException, ValueError):
        synced = None
    if not synced:
        set_state(job, lyrics="not found")
        return ""
    lines = []
    for raw in synced.splitlines():
        m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)", raw.strip())
        if m:
            lines.append({"time": int(m.group(1)) * 60 + float(m.group(2)), "text": m.group(3).strip()})
    json.dump({"lines": lines}, open(path, "w"))
    set_state(job, lyrics="%d lines" % len(lines))
    return path


def word_map(d, job, label, lyrics=""):
    path = os.path.join(d, "words.json")
    if not os.path.exists(path):
        if not os.path.exists(WX):
            return []
        set_state(job, progress="finding words in " + label)
        here = os.path.dirname(os.path.abspath(__file__))
        try:
            run([WX, os.path.join(here, "wordmap.py"), os.path.join(d, "vocals.wav"), path, lyrics])
        except RuntimeError as e:
            set_state(job, word_error=str(e)[:300])
            return []
    return json.load(open(path)).get("words", [])


def pitch_track(path):
    y, _ = librosa.load(path, sr=ASR, mono=True)
    f0, voiced, _ = librosa.pyin(y, fmin=65, fmax=1000, sr=ASR, hop_length=HOP)
    return np.where(voiced & ~np.isnan(f0), librosa.hz_to_midi(np.where(np.isnan(f0), 1.0, f0)), np.nan)


def mid_pitch(track, start, end):
    ft = HOP / ASR
    seg = track[int(start / ft):max(int(start / ft) + 1, int(end / ft))]
    seg = seg[~np.isnan(seg)]
    return round(float(np.median(seg)), 2) if len(seg) else None


def plan_from_words(target, words, track):
    n, m = len(target), len(words)
    items = []
    if n == 0 or m == 0:
        return items
    fallback = mid_pitch(track, 0, 10 ** 6) or 60.0

    def add(t, s0, s1, word):
        sm = mid_pitch(track, s0, s1)
        items.append({"i": len(items), "start": t["start"], "end": t["end"], "midi": t["midi"],
                      "level": t.get("level", 0), "word": word,
                      "src_start": round(s0, 4), "src_end": round(s1, 4),
                      "src_midi": sm if sm is not None else fallback,
                      "shift_ms": 0, "semis": 0, "trim_start_ms": 0, "trim_end_ms": 0,
                      "mute": False})

    if m <= n:
        for j, w in enumerate(words):
            k0 = j * n // m
            k1 = max(k0 + 1, (j + 1) * n // m)
            group = target[k0:k1]
            span = (w["end"] - w["start"]) / len(group)
            for g, t in enumerate(group):
                add(t, w["start"] + g * span, w["start"] + (g + 1) * span, w["word"] if g == 0 else "")
    else:
        for i, t in enumerate(target):
            j0 = i * m // n
            j1 = max(j0 + 1, (i + 1) * m // n)
            ws = words[j0:j1]
            add(t, ws[0]["start"], ws[-1]["end"], " ".join(w["word"] for w in ws))
    return items


def find_notes(path):
    y, _ = librosa.load(path, sr=ASR, mono=True)
    f0, voiced, _ = librosa.pyin(y, fmin=65, fmax=1000, sr=ASR, hop_length=HOP)
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    gate = max(1e-4, float(np.percentile(rms, 60)) * 0.25)
    midi = librosa.hz_to_midi(np.where(np.isnan(f0), 1.0, f0))
    ft = HOP / ASR
    raw, cur = [], None
    for i in range(len(f0)):
        ok = bool(voiced[i]) and not np.isnan(f0[i]) and rms[min(i, len(rms) - 1)] > gate
        if ok and cur and abs(midi[i] - np.median(cur["m"])) < 0.8:
            cur["m"].append(midi[i]); cur["e"] = i
            continue
        if cur:
            raw.append(cur)
        cur = {"s": i, "e": i, "m": [midi[i]]} if ok else None
    if cur:
        raw.append(cur)
    merged = []
    for n in raw:
        if merged:
            p = merged[-1]
            gap = (n["s"] - p["e"]) * ft
            if gap < 0.06 and abs(np.median(n["m"]) - np.median(p["m"])) < 0.6:
                p["m"] += n["m"]; p["e"] = n["e"]
                continue
        merged.append(n)
    out = []
    for n in merged:
        if (n["e"] - n["s"] + 1) * ft < 0.1:
            continue
        seg = rms[n["s"]:n["e"] + 1]
        out.append({"start": round(n["s"] * ft, 4), "end": round((n["e"] + 1) * ft, 4),
                    "midi": round(float(np.median(n["m"])), 2),
                    "level": round(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0, 5)})
    return out


def build_plan(target_notes, source_notes):
    n, m = len(target_notes), len(source_notes)
    items = []
    if n == 0 or m == 0:
        return items
    for i, t in enumerate(target_notes):
        s = source_notes[min(m - 1, i * m // n)]
        items.append({"i": i, "start": t["start"], "end": t["end"], "midi": t["midi"],
                      "level": t.get("level", 0),
                      "src_start": s["start"], "src_end": s["end"], "src_midi": s["midi"],
                      "shift_ms": 0, "semis": 0, "trim_start_ms": 0, "trim_end_ms": 0,
                      "mute": False})
    return items


def bend(vocal, items, total_len):
    out = np.zeros(total_len, dtype=np.float32)
    fade = int(0.012 * SR)
    for it in items:
        if it.get("mute"):
            continue
        a = int((it["src_start"] + it.get("trim_start_ms", 0) / 1000) * SR)
        b = int((it["src_end"] - it.get("trim_end_ms", 0) / 1000) * SR)
        if b - a < int(0.02 * SR):
            continue
        seg = vocal[a:b]
        want = (it["end"] - it["start"]) * SR
        if want < 0.02 * SR:
            continue
        rate = float(np.clip(len(seg) / want, 0.25, 4.0))
        steps = float(np.clip(it["midi"] - it["src_midi"] + it.get("semis", 0), -24, 24))
        piece = pyrb.time_stretch(seg, SR, rate, rbargs={"--pitch": "%.3f" % steps})
        piece = piece.astype(np.float32)
        have = float(np.sqrt(np.mean(piece ** 2))) if len(piece) else 0.0
        want_level = float(it.get("level") or 0)
        if have > 1e-5 and want_level > 0:
            piece *= float(np.clip(want_level / have, 0.1, 10.0))
        f = min(fade, len(piece) // 2)
        if f > 0:
            ramp = np.linspace(0, 1, f, dtype=np.float32)
            piece[:f] *= ramp
            piece[-f:] *= ramp[::-1]
        p = int((it["start"] + it.get("shift_ms", 0) / 1000) * SR)
        if p < 0:
            piece, p = piece[-p:], 0
        end = min(total_len, p + len(piece))
        if end > p:
            out[p:end] += piece[:end - p]
    return out


def eleven(vocal_path, voice_id):
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key or not voice_id:
        return None
    with open(vocal_path, "rb") as fh:
        res = requests.post(
            "https://api.elevenlabs.io/v1/speech-to-speech/%s?output_format=mp3_44100_128" % voice_id,
            headers={"xi-api-key": key},
            files={"audio": ("vocal.wav", fh, "audio/wav")},
            data={"model_id": "eleven_multilingual_sts_v2"}, timeout=600)
    res.raise_for_status()
    return res.content


def render(job):
    d = job_dir(job)
    meta = json.load(open(os.path.join(d, "meta.json")))
    plan = json.load(open(os.path.join(d, "plan.json")))
    set_state(job, status="working", progress="bending")
    vocal, _ = librosa.load(os.path.join(meta["dir2"], "vocals.wav"), sr=SR, mono=True)
    inst, _ = librosa.load(os.path.join(meta["dir1"], "instrumental.wav"), sr=SR, mono=False)
    if inst.ndim == 1:
        inst = np.vstack([inst, inst])
    bent = bend(vocal, plan["items"], inst.shape[1])
    bent_path = os.path.join(d, "bent_vocal.wav")
    sf.write(bent_path, bent, SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", bent_path, "-b:a", "192k",
                    os.path.join(d, "bent_vocal.mp3")], check=True)
    final = bent
    voice = meta.get("voice_id") or os.environ.get("ELEVENLABS_VOICE_ID", "")
    if voice and os.environ.get("ELEVENLABS_API_KEY"):
        set_state(job, progress="singing with elevenlabs")
        audio = eleven(bent_path, voice)
        mp = os.path.join(d, "sung_vocal.mp3")
        open(mp, "wb").write(audio)
        sung, _ = librosa.load(mp, sr=SR, mono=True)
        final = np.zeros_like(bent)
        final[:min(len(sung), len(final))] = sung[:len(final)]
    set_state(job, progress="mixing")
    inst_level = float(np.sqrt(np.mean(inst ** 2))) or 1e-3
    loud = final[np.abs(final) > 1e-4]
    voc_level = float(np.sqrt(np.mean(loud ** 2))) if len(loud) else 0.0
    if voc_level > 1e-5:
        final = final * (inst_level * 1.4 / voc_level)
    mix = inst + final[None, :]
    peak = float(np.max(np.abs(mix))) or 1.0
    mix = mix / max(peak, 1.0) * 0.98
    wav = os.path.join(d, "mix.wav")
    sf.write(wav, mix.T, SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-b:a", "192k",
                    os.path.join(d, "mix.mp3")], check=True)
    os.remove(wav)
    rev = int(r.hget("sb:job:" + job, "rev") or 0) + 1
    set_state(job, status="done", progress="done", rev=rev)


def run_job(job):
    try:
        d = job_dir(job)
        meta = json.load(open(os.path.join(d, "meta.json")))
        set_state(job, status="working")
        if meta.get("ccmixter"):
            import ccmixter
            set_state(job, progress="picking songs on ccmixter")
            picked = ccmixter.pick(meta["ccmixter"])
            meta.update(picked)
        secs = int(meta.get("seconds", 30) or 0)
        dir1, t1 = fetch_and_split(meta["song1"], job, "song one", True, secs)
        dir2, t2 = fetch_and_split(meta["song2"], job, "song two", False, secs)
        meta.update({"dir1": dir1, "dir2": dir2, "title1": t1, "title2": t2})
        json.dump(meta, open(os.path.join(d, "meta.json"), "w"))
        set_state(job, title1=t1, title2=t2, progress="reading melody of song one")
        target = find_notes(os.path.join(dir1, "vocals.wav"))
        lyr = fetch_lyrics(dir2, meta["song2"], job, "song two")
        words = word_map(dir2, job, "song two", lyr)
        set_state(job, progress="reading syllables of song two")
        if len(words) >= 3:
            track = pitch_track(os.path.join(dir2, "vocals.wav"))
            plan = {"items": plan_from_words(target, words, track), "mode": "words"}
        else:
            source = find_notes(os.path.join(dir2, "vocals.wav"))
            plan = {"items": build_plan(target, source), "mode": "notes"}
        set_state(job, plan_mode=plan["mode"], words=len(words))
        json.dump(plan, open(os.path.join(d, "plan.json"), "w"))
        render(job)
    except Exception as e:
        set_state(job, status="error", progress="error", error=str(e)[:500])
        raise


def rerender(job):
    try:
        render(job)
    except Exception as e:
        set_state(job, status="error", progress="error", error=str(e)[:500])
        raise
