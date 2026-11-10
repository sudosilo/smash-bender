Smash Bender

Smash Bender is a processing server for song mashups, with scripts for the phone. It is for the person building the smash tools.

The server splits a song into vocals and music, reads the melody, bends one vocal onto the timing and notes of another, and mixes the result. Word timing comes from the real lyrics, so each word is cut on its true edges. Helper scripts on the phone start jobs and download the results, and a scorer checks how well the words matched. A sample log page tracks every run, and an import endpoint lets other apps start a project.

Latest change. 2026-11-09, v2026.11.09. Added a chop tool that cuts a slice from a sample, reads its notes, and writes Strudel code with a link to open it. Chop timing is exact, the notes are cleaner, and the original slice plays in sync under the notes. The sample log can chop any sample into notes, save a slice to GitHub, and add a sound clip. A publish endpoint sends clips to the Strudel sample repo.

The full history is in CHANGELOG.md.
