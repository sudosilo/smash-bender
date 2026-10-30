#!/bin/bash
# usage: sbjob.sh SONG1 SONG1_ARTIST SONG1_TRACK SONG2 SONG2_ARTIST SONG2_TRACK [SECONDS] [overlay]
# SONG1 is a full-song file, or INSTRUMENTAL_FILE,ACAPELLA_FILE (comma, no space) to skip splitting
# SONG2 is a full-song file, or acap:ACAPELLA_FILE to skip splitting
# SONG1 can also be inst:INSTRUMENTAL_FILE; overlay lays song two's voice on song one's music untouched
cd /opt/smash-bender && . ./.env
BODY=$(python3 -c '
import json, sys
a = sys.argv[1:]
inbox = "/opt/smash-bender/data/inbox/"
def spec(f, artist, track):
    s = {"title": track, "artist": artist, "track": track}
    if "," in f:
        i, v = f.split(",", 1)
        s.update(instrumental_file=inbox + i, vocals_file=inbox + v)
    elif f.startswith("acap:"):
        s["vocals_file"] = inbox + f[5:]
    elif f.startswith("inst:"):
        s["instrumental_file"] = inbox + f[5:]
    else:
        s["file"] = inbox + f
    return s
print(json.dumps({"song1": spec(a[0], a[1], a[2]), "song2": spec(a[3], a[4], a[5]),
                  "seconds": int(a[6]) if len(a) > 6 else 45,
                  "overlay": len(a) > 7 and a[7] == "overlay"}))
' "$@")
J=$(curl -s -X POST -H "x-sb-key: $SB_TOKEN" -H "content-type: application/json" -d "$BODY" 127.0.0.1:8110/jobs | python3 -c 'import sys,json;print(json.load(sys.stdin)["job"])')
echo JOB $J
echo $J > /opt/smash-bender/last_job
while true; do
  S=$(curl -s -H "x-sb-key: $SB_TOKEN" 127.0.0.1:8110/jobs/$J)
  echo "$S"
  echo "$S" | grep -qE '"status":"(done|error)"' && break
  sleep 15
done
echo LISTEN smash-bender.167-233-137-169.sslip.io/files/$J/mix.mp3
