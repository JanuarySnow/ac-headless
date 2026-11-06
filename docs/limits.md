# Limits and known gaps

- Only AC 1.16.4 (Steam build 14923034). The tool checks `acs.exe` and refuses anything else, because every memory address in `achl/offsets.py` belongs to that build.
- Steam has to be running and logged in. On Linux the Windows Steam client runs inside the Wine prefix, see `docs/linux.md`. A full run on a prefix made by `install.sh` has not been tried yet, only on a prefix set up by hand with the same libraries. The terminal login has been tried with a made-up account only, so Steam Guard has not been seen through it yet.
- In a race your car is driven by the AI too. With `--no-drive` it stays parked on the grid and the cars behind it have to get round it, so put it at the back with `starting_position`.
- Grid size is limited by the track's pit boxes.
- Damage, tyre temperatures and wear are not read yet. `tyre_compound` is the compound index only.
- Custom Shaders Patch and Python apps are not supported in headless runs. If `dwrite.dll` is in the AC folder you get a warning.
- `hotlap` runs as a long practice session with the AI driving from the pits, so the first lap includes the pit exit.
- The AI's lap target is set very high so it never stops on its own. The tool ends the run when your lap count or session is done.
- A race run ends as soon as the game marks the session over, which happens when the leader finishes. Cars behind the leader show one lap fewer than the race length.
- One game per run. Running several at once is possible by hand with separate output folders, but the tool does not manage it.
- Telemetry is sampled from outside the game at `--hz`. It is not every physics step.
