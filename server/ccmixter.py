import re, json, random
import http.client
import requests

http.client._MAXLINE = 1 << 24
http.client._MAXHEADERS = 1000

API = "https://ccmixter.org/api/query"
AUDIO = (".mp3", ".flac", ".wav", ".ogg")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
      "Referer": "https://ccmixter.org/"}


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


def reachable(link):
    try:
        res = requests.get(link, headers=dict(UA, Range="bytes=0-2047"), stream=True, timeout=30)
        ok = res.status_code in (200, 206)
        res.close()
        return ok
    except requests.RequestException:
        return False


def label(u):
    return "%s by %s" % (u.get("upload_name", "?"), u.get("user_name", "?"))


def pick(bpm_tag):
    pells = acappellas(bpm_tag)
    if len(pells) < 2:
        raise RuntimeError("ccmixter: fewer than two a cappellas tagged " + bpm_tag)
    random.shuffle(pells)
    good = {}

    def usable(u):
        k = u["upload_id"]
        if k not in good:
            good[k] = reachable(audio_url(u))
        return good[k]

    for a in pells[:20]:
        if not usable(a):
            continue
        mix = next((m for m in remixes_of(a["upload_id"])[:5] if usable(m)), None)
        if not mix:
            continue
        b = next((p for p in pells if p["upload_id"] != a["upload_id"] and usable(p)), None)
        if not b:
            continue
        return {
            "song1": {"url": audio_url(mix), "title": label(mix)},
            "song2": {"vocals_url": audio_url(b), "title": label(b)},
        }
    raise RuntimeError("ccmixter: no a cappella at " + bpm_tag + " with a remix found")
