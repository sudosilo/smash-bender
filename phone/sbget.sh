#!/bin/bash
# usage: sbget.sh NAME "search words"   (downloads on this phone, sends to Frankenfurter inbox as NAME.audio)
set -e
mkdir -p ~/smash-bender && cd ~/smash-bender
rm -f "$1.audio"
yt-dlp -q --no-warnings -f bestaudio --no-playlist -o "$1.audio" "ytsearch1:$2"
ssh frankenfurter "mkdir -p /opt/smash-bender/data/inbox"
scp -q "$1.audio" frankenfurter:/opt/smash-bender/data/inbox/
echo "SENT $1.audio"
