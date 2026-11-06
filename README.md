# ac-headless

Run Assetto Corsa headless with no gpu output, on a linux server or a Windows machine.

It works by starting `acs.exe` with a small DLL loaded into it. The DLL turns off rendering, audio and input, and points the game at its own Documents folder, so your normal AC settings and `race.ini` are never touched.

## What you need

- Assetto Corsa from Steam.
- Steam running and logged in. AC will not start without it. On Linux the tool starts it for you.
- Python 3.9 or newer.
- Custom Shaders Patch turned off for headless runs (rename `dwrite.dll` in the AC folder). Havnt worked out how to let it start with CSP too yet becuse CSP also injects its own stuff at runtime.

## Windows

1. Build the DLL and launcher. From a "x64 Native Tools Command Prompt for VS":

   ```
   native\build.bat
   ```

   This puts `achl.dll` and `achl_launch.exe` in `native\build`. If you got them from a release zip instead, put them in a `bin` folder next to this README.

2. Install into your AC folder:

   ```
   install.bat "C:\Program Files (x86)\Steam\steamapps\common\assettocorsa"
   ```

   This adds an `achl` folder inside the AC folder and nothing else. `uninstall.bat` with the same path removes it again.

3. Run something:

   ```
   run.bat run hotlap --ac "C:\...\assettocorsa" --track magione --car bmw_m3_e30 --laps 3
   ```

You can set `ACHL_AC` to the AC folder once and leave out `--ac`.

## Examples

AI hotlaps in your car, three laps, results in `achl-out`:

```
run.bat run hotlap --track ks_brands_hatch --layout indy --car ks_mazda_mx5_cup --laps 3
```

A five lap race against nine AI, telemetry as JSON lines:

```
run.bat run race --track magione --car bmw_m3_e30 --ai 9 --laps 5 --format jsonl --out out\race1
```

Run the example scenarios and write a JUnit report for CI:

```
run.bat test examples\hotlap.json examples\pit-spawn-check.json --junit report.xml
```

Look at a game that is already running:

```
run.bat probe --watch
```

Every run writes `results.json` (laps, best and mean lap, top speed, time stuck, time off track), `laps.csv`, `telemetry.csv` and the game's own `ac_log.txt` to its output folder. The exit code is 0 when the run or every scenario passed.

There are four example scenarios in `examples/`: a hotlap, an AI race, a pit box spawn check and a lap time regression check. The scenario format is in `docs/scenarios.md`.

## Linux server

All in a terminal, over ssh if you like. AC runs under Wine next to the Windows Steam client, logged in inside the same Wine prefix. Use a Steam account that owns AC.

From this folder:

```
./install.sh --install-ac --steam-user YOUR_ACCOUNT ~/assettocorsa
```

That one command:

1. checks for the programs it needs and offers to install any that are missing
2. makes a Wine prefix in `~/.local/share/ac-headless/prefix` and adds fonts and Direct3D libraries;
3. downloads AC into `~/assettocorsa` with Valve's steamcmd, unless it is already there. steamcmd asks for your password and Steam Guard code itself, and remembers the login
4. takes Steam's DRM wrapper off `acs.exe` with Steamless (https://github.com/atom0s/Steamless) and keeps the original as `acs.exe.steam`;
5. installs the Windows Steam client in the prefix and logs it in. It asks for your account name, password and Steam Guard code here and types them into the hidden Steam window. Leave out `--install-ac` and `--steam-user` if you already have AC.

Then run something:

```
./run.sh run hotlap --ac ~/assettocorsa --track magione --car bmw_m3_e30
```

The tool starts Steam in the background when it needs it. `./run.sh steam status` and `./run.sh steam stop` check on it or close it, and `./run.sh steam login` logs in again. `steam login --qr` shows Steam's QR code in the terminal for the Steam Mobile App instead, and `--vnc` shows the real window through VNC if something looks wrong.

Details are in `docs/linux.md`.

## Limits

- One game per run. Grid size is limited by the track's pit boxes.
- Damage and tyre temperatures are not read yet.
- CSP and Python apps are not supported in headless runs.

More in `docs/limits.md`. The command reference is `docs/cli.md`, and the DLL's switches are in `docs/env.md`.

## Licence

MIT, see `LICENSE`. This tool is not made by or connected with Kunos Simulazioni. You need your own copy of the game.
