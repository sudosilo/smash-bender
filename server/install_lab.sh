#!/bin/bash
# Installs extra audio tools on Frankenfurter for experiments. Each tool is tried on its own,
# so one failure does not stop the rest. Lab tools live in /opt/smash-bender/lab (separate Python).
cd /opt/smash-bender
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -q libchromaprint-tools fluidsynth fluid-soundfont-gm sox libsndfile1 >/dev/null && echo "OK system tools (fpcalc, fluidsynth, sox)" || echo "FAIL system tools"
[ -d lab ] || ~/.local/bin/uv venv -q --python 3.11 lab
for pkg in "numpy<2" librosa soundfile essentia pyworld praat-parselmouth pyacoustid pretty_midi mido music21 madmom crepe; do
  if ~/.local/bin/uv pip install -q --python lab/bin/python "$pkg" >/dev/null 2>&1; then echo "OK $pkg"; else echo "FAIL $pkg"; fi
done
