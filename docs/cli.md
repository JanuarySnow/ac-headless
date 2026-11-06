# Command reference

Run the tool with `run.bat` on Windows or `./run.sh` on Linux. Both pass everything on to `python -m achl`.

The AC folder comes from `--ac`, or from the `ACHL_AC` environment variable when `--ac` is left out.

## install

```
achl install --ac DIR [--from FOLDER]
```

Checks that `acs.exe` is AC 1.16.4, then copies `achl.dll` and `achl_launch.exe` into `DIR/achl/` and writes `DIR/achl/installed.json`. It looks for the two files in `--from`, then `ACHL_BIN`, then `native/build`, then `bin`.

## setup

```
achl setup [--ac DIR | --install-ac DIR] [--steam-user NAME] [--prefix DIR] [--no-steam] [--no-login]
```

Linux only. Makes the Wine prefix, installs fonts and Direct3D libraries with winetricks, downloads AC with steamcmd when `--install-ac` is given and the folder does not have it yet, unpacks `acs.exe` with Steamless, installs the Windows Steam client, and then logs in to Steam in the terminal unless `--no-login` is given or a login is saved. It also takes the login options of `steam login`. `install.sh` runs this for you. Steps that are already done are skipped. See `docs/linux.md`.

## steam

```
achl steam start|stop|status|login [--prefix DIR]
```

Linux only. `start` runs Steam in the background on a hidden display (`--show` for your desktop), `stop` closes it, `status` says whether it is running and logged in and exits 0 only when it is logged in. `login` gets you logged in once: `--type` asks in the terminal and types into the hidden Steam window (default without `DISPLAY`), `--qr` shows Steam's QR code in the terminal, `--vnc` shows the window through VNC on localhost, and `--window` opens it on your desktop (default with `DISPLAY`). `--port` is for VNC and `--timeout` is in seconds, default 900. See `docs/linux.md`.

## uninstall

```
achl uninstall --ac DIR
```

Removes the files listed in `installed.json`, then the `achl` folder if it is empty.

## run

```
achl run hotlap|race|practice --track TRACK --car CAR [options]
```

- `hotlap`: one car, the AI drives it from the pits for `--laps` laps.
- `race`: your car plus `--ai` opponents, standing start, `--laps` laps. Your car is driven by the AI as well.
- `practice`: a practice session of `--minutes` minutes, with or without `--ai` opponents.

Options:

| option | default | what it does |
|---|---|---|
| `--layout` | none | track layout folder |
| `--ai N` | 0 | number of AI opponents |
| `--ai-car CAR` | your car | opponent car, give it more than once for a mixed grid |
| `--ai-level` | 100 | AI skill, 0 to 100 |
| `--ai-aggression` | 0 | AI aggression, 0 to 100 |
| `--laps` | 3 | laps for hotlap and race |
| `--minutes` | 10 | length of a practice run |
| `--timeout` | 900 | stop and fail after this many seconds |
| `--render` | off | `on` keeps the game window and rendering, for watching a run |
| `--no-drive` | | leave your car parked |
| `--hz` | 10 | telemetry samples per second |
| `--format` | csv | `csv`, `jsonl` or `none` |
| `--grip` | 100 | starting track grip in percent |
| `--weather` | 3_clear | weather folder name |
| `--ambient`, `--road` | 22, 28 | temperatures |
| `--memory-max` | | Linux only, cap the game's memory with systemd, for example `3G`. |
| `--prefix` | | Linux only, the Wine prefix with Steam. Default `WINEPREFIX`, then `~/.local/share/ac-headless/prefix` |
| `--out` | `achl-out/<time>-<mode>` | output folder |
| `--results FILE` | | also copy `results.json` to FILE |

Output folder:

- `results.json`: outcome, per car laps, best and mean lap, top speed, distance, longest time stood still, time off track, how far the car dropped below where it started.
- `laps.csv`: one row per completed lap.
- `telemetry.csv` or `telemetry.jsonl`: one row per car per sample. Columns are listed in `docs/scenarios.md`.
- `ac_log.txt`: the game's own log.
- `achl.log`: the DLL's log.
- `profile/`: the private Documents folder the game used for this run.

Exit code 0 means the run finished. 1 means it timed out, crashed or failed to load.

On Linux, `run` and `test` start Steam first if it is not running, and stop with a message if it is not logged in.

## test

```
achl test SCENARIO.json [MORE.json] [--junit report.xml] [--out DIR] [--memory-max 3G] [--prefix DIR]
```

Runs each scenario, checks its assertions and prints PASS or FAIL per check. Writes `report.json` to the output folder, and JUnit XML if asked. Exit code 0 only if every scenario passed.

## probe

```
achl probe [--pid PID] [--ac DIR] [--watch] [--interval 1] [--json]
```

Reads the session and every car from a running `acs.exe`: lap, track position, speed, gear, rpm, fuel, best lap and whether it is AI driven. With `--ac` the build is checked first. On Linux it can only read a game that this tool started, unless your system allows reading other processes (`kernel.yama.ptrace_scope`).
