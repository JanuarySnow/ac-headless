# DLL switches

The DLL reads environment variables when the game starts. `achl run` sets them for you. Any `ACHL_` variable you set yourself is passed through and wins over the defaults, which is handy for trying things.

| variable | what it does |
|---|---|
| `ACHL_DOCS` | folder the game uses as Documents. Gives every run its own `cfg`, logs and `race.ini` |
| `ACHL_LOG` | where the DLL writes its log |
| `ACHL_WARP` | `1` makes Direct3D use Windows' software renderer, so no GPU is needed |
| `ACHL_FAKESWAP` | `1` gives the game an offscreen swap chain when WARP cannot make a real one, for machines with no display at all |
| `ACHL_TEXSHRINK` | `1` loads every content texture as 4x4 pixels |
| `ACHL_BUFSHRINK` | `1` replaces static vertex and index buffers with tiny ones. Physics keeps its own copy of the geometry |
| `ACHL_HIDEWIN` | `1` hides the game window |
| `ACHL_NOAUDIO` | `1` skips loading sound banks |
| `ACHL_NOINPUT` | `1` hides wheels and joysticks from the game, so force feedback is left alone. The keyboard still works when the window has focus |
| `ACHL_SLEEP0_MS` | `1` makes the physics thread sleep 1 ms instead of spinning between steps. Saves about a core with one car, lap times are unchanged |
| `ACHL_RENDER_OFF` | `1` turns rendering off once the session has loaded. It has to wait, because the game loads content from its render loop |
| `ACHL_AUTODRIVE` | `1` starts the session and puts the AI in charge of your car once it has loaded |
| `ACHL_AUTOSTART` | `1` starts the race countdown in an offline race |
| `ACHL_START_DELAY_MS` | countdown length for `ACHL_AUTOSTART`, default 3000 |
| `ACHL_WAIT_S` | how long to wait for the session to load, default 300 |
| `ACHL_STUBDISPLAYMODE` | `1` skips the game's display mode query, for machines where it finds no monitor |
| `ACHL_PTRACER` | Linux only: the process id that may read the game's memory. Set by the tool to itself. Ignored outside Wine |
| `ACHL_RUN_ID` | marks the game process so the tool can find it. Set by the tool |
| `ACHL_OFFSETS` | addresses for this game build. Filled in by the tool from `achl/offsets.py`, do not set by hand |

Defaults used by `achl run --render off`:

- Windows: `WARP`, `FAKESWAP`, `TEXSHRINK`, `BUFSHRINK`, `HIDEWIN`, `NOAUDIO`, `NOINPUT`, `SLEEP0_MS=1`, `RENDER_OFF`.
- Linux: `NOAUDIO`, `NOINPUT`, `RENDER_OFF`. Wine has no WARP, so rendering goes through whatever Direct3D the prefix has.

With `--render on` only `NOINPUT` is set.

Other variables the tool reads:

| variable | what it does |
|---|---|
| `ACHL_AC` | default AC folder |
| `ACHL_BIN` | folder with `achl.dll` and `achl_launch.exe` for install |
| `ACHL_WINE` | wine command on Linux, default `wine` |
| `WINEPREFIX` | the Wine prefix to run in, when `--prefix` is not given. Default `~/.local/share/ac-headless/prefix` |
| `ACHL_STEAM` | `off` stops `run` and `test` from starting or checking Steam on Linux |
| `DISPLAY` | X display. If unset on Linux the tool starts Xvfb and stops it afterwards |
