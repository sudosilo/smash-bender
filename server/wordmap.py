import os, sys, json
import whisperx

src, dest = sys.argv[1], sys.argv[2]
lyrics = sys.argv[3] if len(sys.argv) > 3 else ""
lang = os.environ.get("SB_LANG", "en")
audio = whisperx.load_audio(src)
length = len(audio) / 16000.0
segments = []
if lyrics and os.path.exists(lyrics):
    lines = json.load(open(lyrics)).get("lines", [])
    for i, ln in enumerate(lines):
        start = ln["time"]
        end = lines[i + 1]["time"] if i + 1 < len(lines) else length
        if start < length and ln["text"].strip():
            segments.append({"start": start, "end": min(end, length), "text": ln["text"]})
source = "lyrics" if segments else "listening"
if not segments:
    size = os.environ.get("SB_WHISPER", "small")
    model = whisperx.load_model(size, "cpu", compute_type="int8", language=lang)
    segments = model.transcribe(audio, batch_size=4, language=lang)["segments"]
    del model
align_model, meta = whisperx.load_align_model(language_code=lang, device="cpu")
aligned = whisperx.align(segments, align_model, meta, audio, "cpu", return_char_alignments=False)
words = []
for w in aligned.get("word_segments", []):
    if "start" in w and "end" in w and w["end"] > w["start"]:
        words.append({"word": w.get("word", "").strip(), "start": round(float(w["start"]), 3),
                      "end": round(float(w["end"]), 3)})
json.dump({"language": lang, "source": source, "words": words}, open(dest, "w"))
print(len(words), "words from", source)
