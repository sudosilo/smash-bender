import re, json, random
import requests

API = "https://ccmixter.org/api/query"
AUDIO = (".mp3", ".flac", ".wav", ".ogg")
UA = {"User-Agent": "smash-bender/1.0"}


def query(params):
    url = API + "?" + "&".join("%s=%s" % (k, v) for k, v in params.items())
    res = requests.get(url, headers=UA, timeout=60)
    res.raise_for_status()
    text = re.sub(r'(?<=[:\[,])\s*0+(\d)', r'\1', res.text)
    data = json.loads(text, strict=False)
    return data if isinstance(data, list) else []


def tags_of(u):
    return set(t for t in str(u.get("upload_tags", "")).replace(" ", ",").split(",") if t)


def audio_url(u):
    for f in u.get("files") or []:
        link = f.get("download_url") or ""
        if link.lower().endswith(AUDIO):
            return link
    return ""


def acappellas(bpm_tag):
    found = []
    for joiner in ("+", "%2B", ","):
        rows = query({"f": "json", "tags": "acappella" + joiner + bpm_tag, "type": "all",
                      "limit": "60", "sort": "rank"})
        found = [u for u in rows if {"acappella", bpm_tag} <= tags_of(u) and audio_url(u)]
        if found:
            break
    return found


def remixes_of(upload_id):
    rows = query({"f": "json", "remixes": str(upload_id), "limit": "20", "sort": "rank"})
    return [u for u in rows if audio_url(u) and "acappella" not in tags_of(u)]


def label(u):
    return "%s by %s" % (u.get("upload_name", "?"), u.get("user_name", "?"))


def pick(bpm_tag):
    pells = acappellas(bpm_tag)
    if len(pells) < 2:
        raise RuntimeError("ccmixter: fewer than two a cappellas tagged " + bpm_tag)
    random.shuffle(pells)
    for a in pells[:15]:
        mixes = remixes_of(a["upload_id"])
        if not mixes:
            continue
        b = next(p for p in pells if p["upload_id"] != a["upload_id"])
        return {
            "song1": {"url": audio_url(mixes[0]), "vocals_url": audio_url(a),
                      "title": label(mixes[0])},
            "song2": {"vocals_url": audio_url(b), "title": label(b)},
        }
    raise RuntimeError("ccmixter: no a cappella at " + bpm_tag + " with a remix found")
