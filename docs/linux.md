# Linux

AC runs under Wine. It needs two things there: an `acs.exe` with Steam's DRM wrapper taken off, and the Windows Steam client running and logged in inside the same Wine prefix. `install.sh` sets up both, and `achl steam` looks after the Steam client. All of it works in a terminal over ssh.

You need a Steam account that owns AC. A separate account just for testing is a good idea, because the login stays saved in the prefix.

## What install.sh does

```
./install.sh [--install-ac] [--steam-user NAME] [--prefix DIR] [--no-steam] [--no-login] [--yes] /path/to/assettocorsa
```

In this order:

1. Checks for `python3`, `wine`, `winetricks`, `cabextract`, `Xvfb`, `xdotool`, `mono`, a Vulkan driver, `x86_64-w64-mingw32-gcc` when the DLL is not built yet, and the 32-bit C library when `--install-ac` is given (steamcmd is a 32-bit program). If any are missing it prints the `apt-get`, `dnf` or `pacman` command and asks before running it with sudo. `--yes` runs it without asking. Without a terminal it only prints the command. On Debian and Ubuntu the command also turns on 32-bit packages when Wine is missing, because the Steam installer is a 32-bit program.
2. Builds `achl.dll` and `achl_launch.exe` with mingw-w64 if they are not there.
3. Runs `achl setup`, which:
   - makes the Wine prefix, `~/.local/share/ac-headless/prefix` unless you pass `--prefix`;
   - installs `corefonts`, `tahoma`, `dxvk`, `d3dx11_43`, `d3dcompiler_43` and `d3dcompiler_47` with winetricks. Without the fonts the Steam login window shows no text;
   - downloads Steamless 3.1.0.5 (https://github.com/atom0s/Steamless) when `acs.exe` still needs it;
   - with `--install-ac`, downloads AC into the folder with steamcmd (see below), unless that folder already has AC 1.16.4;
   - runs Steamless on `acs.exe` if it still has the DRM wrapper. The result has to pass the tool's build check before it replaces `acs.exe`, and the original is kept as `acs.exe.steam`. An exe that is already unpacked is left alone;
   - downloads `SteamSetup.exe` from Valve, installs it silently into the prefix, and starts Steam once so it can download its update. Steam ends that first start with exit code 42, which is expected.
4. Runs `achl install` to copy the DLL and launcher into the AC folder.
5. Logs in to the Steam client with `steam login` in the terminal, unless it has a saved login, there is no terminal, or you pass `--no-login`. If the login does not work, install.sh still finishes and tells you the command to try again.

Everything is done in a hidden Xvfb display. Downloads are kept in `~/.cache/ac-headless`. Running `install.sh` again skips the steps that are already done.

To undo it, run `uninstall.sh` with the same path, put `acs.exe.steam` back as `acs.exe` (or let Steam verify the game files), and delete the prefix folder and `~/.local/share/ac-headless/steamcmd`.

## Getting AC with steamcmd

```
./run.sh setup --install-ac DIR [--steam-user NAME]
```

This downloads Valve's steamcmd for Linux into `~/.local/share/ac-headless/steamcmd` and runs:

```
steamcmd +@sSteamCmdForcePlatformType windows +force_install_dir DIR +login NAME +app_update 244210 validate +quit
```

steamcmd asks for the password and the Steam Guard code itself, in the terminal, and keeps the login so later runs do not ask again. The tool never sees the password. If you leave out `--steam-user` it asks for the account name. AC with its DLC is about 10 to 20 GB, and the tool stops before downloading if there are less than 20 GB free.

steamcmd runs with its own home folder inside `~/.local/share/ac-headless/steamcmd`, so it never touches a Steam install that is already in your home folder.

If DIR already has AC 1.16.4, nothing is downloaded. If it has an `acs.exe` this tool does not know, it stops. Once Steamless has unpacked `acs.exe`, do not run `app_update` on that folder yourself: steamcmd would put the DRM exe back, and you would need to run setup again.

## Logging in to Steam

You do this once. Steam keeps the login when Remember me is ticked, which it is by default.

```
./run.sh steam login [--type | --qr | --vnc | --window] [--prefix DIR] [--port N] [--timeout 900]
```

- `--type` is the default when there is no `DISPLAY`. Steam starts on a hidden display. The tool asks for your account name and password in the terminal (the password is not shown), and types them into the Steam window with `xdotool`. It watches the window and Steam's log to see what happened next:
  - signed in: it says so and leaves Steam running;
  - wrong account name or password: it says so and asks again, up to three times;
  - Steam Guard: it asks for the code from the email or the Steam Mobile App, or you approve the sign in in the app and it notices by itself. A wrong code is asked for again, up to three times.

  Nothing you type is put on a command line, in an environment variable or in a file. If nothing is typed in time, Steam does not answer, or you press Ctrl+C, it stops Steam and its hidden display again.
- `--qr` shows Steam's own sign in QR code in the terminal. In the Steam Mobile App, tap the shield, then Scan a QR code. The code is printed again whenever Steam changes it. No password is typed anywhere. Your terminal needs a font that has block characters, which most do.
- `--vnc` shows the real Steam window through `x11vnc`, on localhost only, with a one-time password. The tool prints something like:

  ```
  ssh -N -L 5977:localhost:5977 you@yourserver
  ```

  Run that on your own computer. It prints nothing and looks stuck, but the tunnel is open, so leave it running. Then open a VNC viewer at `localhost:5977` and enter the password. Use this if the other ways get stuck and you want to see the window.
- `--window` is the default when `DISPLAY` is set: the Steam window opens on your desktop.

`--timeout` is the whole time allowed for the login, in seconds.

## Steam in the background

```
./run.sh steam start   [--prefix DIR] [--show]
./run.sh steam status  [--prefix DIR]
./run.sh steam stop    [--prefix DIR]
```

`start` runs Steam on its own hidden Xvfb display and returns. It does nothing if Steam is already running in that prefix. `--show` puts it on your desktop instead.

`status` says whether Steam is installed, running and logged in, and exits 0 only when it is logged in. Logged in means Steam has set its active user in the prefix's registry, which it does once the sign in is complete.

`stop` asks Steam to shut down, waits up to 30 seconds, then ends any Steam processes left in that prefix and its hidden display.

`run` and `test` start Steam themselves when it is not running, wait up to two minutes for it to log in, and stop with "run steam login" if there is no saved login. Steam is left running afterwards so the next run starts quickly. Set `ACHL_STEAM=off` to skip all of this if you look after Steam yourself.

## Why the full Steam client

AC calls `SteamAPI_Init` when it starts. Valve's `steam_api64.dll` finds Steam through the registry key `HKCU\Software\Valve\Steam\ActiveProcess` (the client's process id and the path of `steamclient64.dll`) and then talks to that running client. I checked whether something smaller would do, with Valve's own files only:

- The Windows `steamcmd.exe`, logged in and left running in the same prefix, does not write that registry key. `SteamAPI_IsSteamRunning` and `SteamAPI_Init` both return false.
- With the key pointed at the running `steamcmd.exe` and its own `steamclient64.dll`, `SteamAPI_IsSteamRunning` returns true but `SteamAPI_Init` still fails. steamcmd does not serve games.
- The same test against the Windows Steam client, logged in, in another prefix: `SteamAPI_Init` returns true.

So the full Windows client is needed, and only its login needs any input. The client's documented `-login NAME PASSWORD` switch puts the password on the command line, where other users of the machine can see it, so this tool does not use it.


## Notes

- `--prefix` wins, then `WINEPREFIX`, then the default prefix.
- If `DISPLAY` is not set the game gets its own Xvfb on a free display number, stopped at the end of the run.
- `--memory-max 3G` runs the game in a systemd user scope with that memory cap. That needs a user session bus. Over `sudo` or `su` there is none, so the tool says so and runs without a cap. Logging in as that user directly, or `loginctl enable-linger` once, fixes it.
- The tool reads game memory through `/proc/<pid>/mem`. Wine starts the game detached from the launcher, so on systems with `kernel.yama.ptrace_scope=1` (the Ubuntu default) the DLL tells the kernel that the tool's own process may read it. Nothing else gets that permission. To probe a game from another shell you need `ptrace_scope=0` or root.
- Rendering goes through DXVK, which needs a Vulkan driver. On a machine with no GPU that is Mesa's lavapipe, which comes with `mesa-vulkan-drivers` on Debian, Ubuntu and Fedora.
- The hidden displays this tool starts use a private X authority file, so other users on the machine cannot connect to them or read the login window.
