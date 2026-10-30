#!/bin/bash
# usage: sbjob.sh SONG1_FILE SONG1_ARTIST SONG1_TRACK SONG2_FILE SONG2_ARTIST SONG2_TRACK [SECONDS]
cd /opt/smash-bender && . ./.env
BODY=$(python3 -c '
import json, sys
a = sys.argv[1:]
inbox = "/opt/smash-bender/data/inbox/"
print(json.dumps({"song1": {"file": inbox + a[0], "title": a[2], "artist": a[1], "track": a[2]},
                  "song2": {"file": inbox + a[3], "title": a[5], "artist": a[4], "track": a[5]},
                  "seconds": int(a[6]) if len(a) > 6 else 45}))
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
