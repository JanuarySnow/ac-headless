# How it works

1. `achl run` checks `acs.exe` against the known builds, writes a `race.ini` and a small set of low quality settings into a fresh profile folder, and works out the DLL switches.
2. `achl_launch.exe` starts `acs.exe` suspended, loads `achl.dll` into it, then lets it run. It stays open until the game exits, and the game is in a job object so it dies with the launcher. On Linux the launcher runs under Wine.
3. The DLL hooks a few imports before the game gets going: the Documents folder lookup, Direct3D device creation, window creation, DirectInput, the sound bank loader and `Sleep`.
4. Once the session has loaded, the DLL starts it, gives your car to the AI, starts the race countdown in a race, and turns rendering off.
5. Meanwhile the tool reads game memory from outside a set number of times a second, writes telemetry, tracks laps, and stops the game when the run is done.

All game addresses live in `achl/offsets.py`. The tool passes the ones the DLL needs to it in `ACHL_OFFSETS`, so the DLL has none built in.

## Building

- Windows: `native\build.bat` from a Visual Studio x64 tools prompt.
- Linux or WSL: `native/build.sh`, needs `x86_64-w64-mingw32-gcc`. The result runs on Windows too.

## Running the unit tests

```
python -m unittest discover -s tests
```

They need no game and no Windows.
