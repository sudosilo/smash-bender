import os, subprocess
import redis

# Runs a stage one experiment (experiment.py in the lab python) for the web page, in the worker.
BASE = os.environ.get("SB_BASE", "/opt/smash-bender")
r = redis.Redis(decode_responses=True)


def run_experiment(job_id, inst_file, acap_file, project, seconds, song_one, song_two, music_start=0.0, voice_start=0.0):
    state = "sb:stage2:" + job_id
    r.hset(state, mapping={"status": "working", "progress": "measuring key and tempo, then making 4 samples"})
    res = subprocess.run([os.path.join(BASE, "lab", "bin", "python"), os.path.join(BASE, "repo", "server", "experiment.py"),
                          inst_file, acap_file, project, str(seconds), "4", song_one, song_two,
                          "%.3f" % float(music_start or 0), "%.3f" % float(voice_start or 0)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        tail = [l for l in res.stderr.strip().splitlines() if "INFO" not in l and "WARNING" not in l][-1:] or ["failed"]
        r.hset(state, mapping={"status": "error", "progress": "error", "error": tail[0][:300]})
        raise RuntimeError(tail[0])
    r.hset(state, mapping={"status": "done", "progress": "done"})
