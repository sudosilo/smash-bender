import os, sys, json
import whisperx

src, dest = sys.argv[1], sys.argv[2]
size = os.environ.get("SB_WHISPER", "small")
audio = whisperx.load_audio(src)
model = whisperx.load_model(size, "cpu", compute_type="int8")
result = model.transcribe(audio, batch_size=4)
lang = result.get("language", "en")
del model
align_model, meta = whisperx.load_align_model(language_code=lang, device="cpu")
aligned = whisperx.align(result["segments"], align_model, meta, audio, "cpu",
                         return_char_alignments=False)
words = []
for w in aligned.get("word_segments", []):
    if "start" in w and "end" in w and w["end"] > w["start"]:
        words.append({"word": w.get("word", "").strip(), "start": round(float(w["start"]), 3),
                      "end": round(float(w["end"]), 3)})
json.dump({"language": lang, "words": words}, open(dest, "w"))
print(len(words), "words")
