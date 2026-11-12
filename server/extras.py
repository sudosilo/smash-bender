import os, shutil
from fastapi import APIRouter
from fastapi.responses import FileResponse

# Extra pages and endpoints live here so new features do not need edits to app.py.
router = APIRouter()
BASE = os.environ.get("SB_BASE", "/opt/smash-bender")
HERE = os.path.dirname(os.path.abspath(__file__))


def py(env):
    return os.path.exists(os.path.join(BASE, env, "bin", "python"))


def has(module, env):
    lib = os.path.join(BASE, env, "lib")
    if not os.path.isdir(lib):
        return False
    for v in os.listdir(lib):
        sp = os.path.join(lib, v, "site-packages")
        if os.path.isdir(sp) and any(n == module or n.startswith(module + "-") or n.startswith(module + ".")
                                      for n in os.listdir(sp)):
            return True
    return False


def tools():
    key = bool(os.environ.get("ELEVENLABS_API_KEY"))
    gh = bool(os.environ.get("GITHUB_TOKEN"))
    T = []

    def add(group, name, what, ready, used, note=""):
        T.append({"group": group, "name": name, "what": what, "ready": bool(ready), "used_by": used, "note": note})

    add("Getting the audio", "yt-dlp", "Downloads songs from YouTube. Runs on the phones, because YouTube blocks this server.",
        True, "The phone download helper and the Smash Director relay", "Lives on the phone, not here")
    add("Getting the audio", "Demucs", "Splits a full song into the voice and the music.",
        has("demucs", "venv"), "Older full-song jobs; not needed when you upload a ready-made instrumental and a cappella")
    add("Getting the audio", "FFmpeg", "Cuts, trims and converts audio files.", shutil.which("ffmpeg"), "Every step")

    add("Reading the audio", "Essentia", "Finds a track's musical key and tempo, and where the beats fall.",
        has("essentia", "lab"), "Start experiment (key matched and tempo matched samples), Auto-Tune")
    add("Reading the audio", "Basic Pitch", "Turns a voice or melody into notes: which note, when it starts, how long it lasts.",
        has("basic_pitch", "bp"), "Chop into notes, Send to Instrument")
    add("Reading the audio", "pYIN (librosa)", "Follows the pitch of a voice moment by moment.",
        has("librosa", "venv"), "Older word-bending jobs and the benchmark score")
    add("Reading the audio", "WhisperX", "Hears the words in a recording and when each word is sung.",
        has("whisperx", "wx"), "The Words heard score on every sample; word maps in older bending jobs")
    add("Reading the audio", "LRCLIB lyrics", "Looks up a song's real lyrics with line timings.",
        True, "Older word-bending jobs, to help WhisperX place words", "A free web service, nothing installed")
    add("Reading the audio", "Chromaprint", "Makes an audio fingerprint, to measure how much one recording sounds like another.",
        shutil.which("fpcalc"), "The Music, Voice and Both scores on every sample")

    add("Changing the audio", "Rubber Band", "Stretches a recording longer or shorter and shifts it higher or lower.",
        shutil.which("rubberband"), "Start experiment (key matched and tempo matched samples); older word-bending jobs")
    add("Changing the audio", "WORLD", "Takes a voice apart and rebuilds it on new notes. This is the Auto-Tune.",
        has("pyworld", "lab"), "Send to Auto-Tune")
    add("Changing the audio", "ElevenLabs", "Re-sings a voice in a different, cleaner voice, keeping the timing and notes.",
        key, "Send to ElevenLabs", "" if key else "Needs the ElevenLabs API key on this server")
    add("Changing the audio", "FluidSynth", "Plays notes on sampled instruments: piano, strings, trumpet, synth.",
        shutil.which("fluidsynth"), "Send to Instrument")

    add("Sending it out", "Strudel", "A live-coding music page. A chopped phrase opens there as notes you can loop and edit.",
        True, "Open in Strudel, on any chop", "Runs in the browser, nothing installed")
    add("Sending it out", "GitHub sample repo", "Keeps saved sound clips where Strudel can load them by name.",
        gh, "Save slice to GitHub, Add sound clip", "" if gh else "Needs the GitHub login on this server")

    add("Installed, not wired in yet", "Praat", "Voice analysis and pitch editing, another way to retune a voice.",
        has("parselmouth", "lab"), "Nothing yet")
    add("Installed, not wired in yet", "AcoustID", "Names a recording by looking its fingerprint up in a public database.",
        has("acoustid", "lab") or has("pyacoustid", "lab"), "Nothing yet", "Needs a free AcoustID key before it can look songs up")
    add("Installed, not wired in yet", "music21", "Music theory helper: scales, chords, harmony lines.",
        has("music21", "lab"), "Nothing yet")
    add("Installed, not wired in yet", "Claude Code", "Claude working directly on this server: reading results, changing code, rerunning.",
        os.path.exists(os.path.expanduser("~/.local/bin/claude")), "Nothing yet", "Installed, still needs its sign-in")
    return T


@router.get("/api/tools")
def api_tools():
    return tools()


@router.get("/tools")
def tools_page():
    return FileResponse(os.path.join(HERE, "static", "tools.html"), media_type="text/html")
