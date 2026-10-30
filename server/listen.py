import os, sys, json, re, difflib
import whisperx

# usage: listen.py REFERENCE_ACAPELLA_WAV MIX_FILE CACHE_JSON   (WhisperX python)
# Prints JSON: what was heard in the mix, and how many of the a cappella's own words come through.
ref, mix, cache = sys.argv[1], sys.argv[2], sys.argv[3]


def norm(w):
    return re.sub(r"[^a-z0-9']", "", (w or "").lower())


model = None


def hear(path):
    global model
    if model is None:
        model = whisperx.load_model(os.environ.get("SB_WHISPER", "small"), "cpu", compute_type="int8", language="en")
    audio = whisperx.load_audio(path)
    return " ".join(s["text"].strip() for s in model.transcribe(audio, batch_size=4, language="en")["segments"])


if os.path.exists(cache):
    ref_text = json.load(open(cache))["text"]
else:
    ref_text = hear(ref)
    json.dump({"text": ref_text}, open(cache, "w"))
mix_text = hear(mix)
a = [norm(w) for w in ref_text.split() if norm(w)]
b = [norm(w) for w in mix_text.split() if norm(w)]
got = sum(m.size for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
print(json.dumps({"reference_words": len(a), "understood": got,
                  "understood_pct": round(100.0 * got / max(1, len(a)), 1), "heard": mix_text[:400]}))
