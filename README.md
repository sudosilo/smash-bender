Smash Bender

Smash Bender is a processing server for song mashups, with scripts for the phone. It is for the person building the smash tools.

The server splits a song into vocals and music, reads the melody, bends one vocal onto the timing and notes of another, and mixes the result. Word timing comes from the real lyrics, so each word is cut on its true edges. Helper scripts on the phone start jobs and download the results, and a scorer checks how well the words matched. A sample log page tracks every run, and an import endpoint lets other apps start a project.

Latest change. 2026-10-30, v2026.10.30. Added a listening check for words understood and sounds-like, a key strength reading from singing loudness, and a lab toolbox installer. Added an overlay baseline that puts one song's voice on another's music untouched, and a melody reader that plays an acapella's tune on piano. Ready-made instrumental and acapella files now skip splitting. Experiments run in a capped loop that logs the idea, the change, and the measurements for each run, and a sample log page shows every run set with pads, scores, ratings, and a progress trend. Added stages two and three with Auto-Tune and a voice tool, an Instrument tool, projects with uploads, an import endpoint other apps can call, and clips that start partway into each song.

The full history is in CHANGELOG.md.
