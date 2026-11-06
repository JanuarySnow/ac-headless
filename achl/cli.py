import argparse
import json
import os
import shutil
import signal
import sys
import time

from . import __version__, drive, launch, linuxsetup, login, memory, offsets, scenario, state, steam

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = "installed.json"


def ac_dir_from(args):
    d = args.ac or os.environ.get("ACHL_AC")
    if not d:
        sys.exit("say where AC is with --ac or the ACHL_AC environment variable")
    if not os.path.isfile(os.path.join(d, "acs.exe")):
        sys.exit("no acs.exe in %s" % d)
    return os.path.abspath(d)


def find_binaries(src):
    places = [src] if src else [os.environ.get("ACHL_BIN"),
                                os.path.join(REPO, "native", "build"), os.path.join(REPO, "bin")]
    for p in places:
        if p and all(os.path.isfile(os.path.join(p, f)) for f in (launch.DLL, launch.LAUNCHER)):
            return p
    sys.exit("achl.dll and achl_launch.exe not found. Build them with native/build.bat or "
             "native/build.sh, or pass --from with the folder that has them")


def check_build(ac):
    try:
        version, kind = offsets.identify(os.path.join(ac, "acs.exe"))
    except offsets.UnknownBuild as e:
        sys.exit(str(e))
    return version, kind


APP_ID = "244210"


def cmd_install(args):
    ac = ac_dir_from(args)
    version, kind = check_build(ac)
    src = find_binaries(args.src)
    dest = os.path.join(ac, launch.INSTALL_DIR)
    os.makedirs(dest, exist_ok=True)
    files = []
    for f in (launch.DLL, launch.LAUNCHER):
        shutil.copyfile(os.path.join(src, f), os.path.join(dest, f))
        files.append(os.path.join(launch.INSTALL_DIR, f))
    appid = os.path.join(ac, "steam_appid.txt")
    if not os.path.isfile(appid):
        with open(appid, "w", encoding="ascii") as fh:
            fh.write(APP_ID)
        files.append("steam_appid.txt")
        print("added steam_appid.txt, which AC needs when Steam does not start it")
    with open(os.path.join(dest, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump({"version": __version__, "ac_version": version, "files": files}, fh, indent=2)
    print("installed into %s (AC %s, %s exe)" % (dest, version, kind))
    if os.path.isfile(os.path.join(ac, "dwrite.dll")):
        print("note: Custom Shaders Patch is installed here; headless runs are tested without it")
    if not launch.IS_WINDOWS and kind == "steam":
        print("note: this acs.exe still has Steam's DRM wrapper, which does not run under Wine. "
              "install.sh unpacks it, see docs/linux.md")
    return 0


def cmd_uninstall(args):
    ac = ac_dir_from(args)
    dest = os.path.join(ac, launch.INSTALL_DIR)
    man = os.path.join(dest, MANIFEST)
    if not os.path.isfile(man):
        print("nothing installed in %s" % ac)
        return 0
    with open(man, encoding="utf-8") as fh:
        files = json.load(fh).get("files", [])
    for rel in files:
        p = os.path.join(ac, rel)
        if os.path.isfile(p):
            os.remove(p)
    os.remove(man)
    try:
        os.rmdir(dest)
    except OSError:
        print("left %s in place because it has other files in it" % dest)
    print("removed achl from %s" % ac)
    return 0


def spec_from_args(args, mode):
    return {"mode": mode, "track": args.track, "layout": args.layout, "car": args.car,
            "ai": args.ai, "ai_level": args.ai_level, "ai_aggression": args.ai_aggression,
            "ai_cars": args.ai_car or None, "laps": args.laps, "minutes": args.minutes,
            "timeout": args.timeout, "render": args.render, "hz": args.hz, "format": args.format,
            "drive": not args.no_drive, "memory_max": args.memory_max, "grip": args.grip,
            "weather": args.weather, "ambient": args.ambient, "road": args.road}


def out_dir_from(args, name):
    if args.out:
        return os.path.abspath(args.out)
    return os.path.abspath(os.path.join("achl-out", "%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), name)))


def linux_steam(args):
    if launch.IS_WINDOWS:
        return
    prefix = steam.prefix_from(args.prefix)
    os.environ["WINEPREFIX"] = prefix
    try:
        steam.ensure_ready(prefix)
    except steam.SteamError as e:
        sys.exit(str(e))


def login_mode(args):
    if args.mode:
        return args.mode
    return "window" if os.environ.get("DISPLAY") else "type"


def do_login(prefix, mode, port=None, timeout=900):
    try:
        ok = login.run(prefix, mode, port=port, timeout=timeout)
    except steam.SteamError as e:
        print(str(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130
    print("Steam is logged in" if ok else "gave up waiting for the login")
    return 0 if ok else 1


def cmd_setup(args):
    if launch.IS_WINDOWS:
        sys.exit("setup is for Linux. On Windows install Steam and AC the normal way")
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, login._interrupt)
    if args.install_ac:
        ac = os.path.abspath(os.path.expanduser(args.install_ac))
    else:
        ac = ac_dir_from(args) if args.ac or os.environ.get("ACHL_AC") else None
    prefix = steam.prefix_from(args.prefix)
    try:
        linuxsetup.setup(ac, prefix, with_steam=not args.no_steam, get_ac=bool(args.install_ac),
                         steam_user=args.steam_user)
    except (linuxsetup.SetupError, steam.SteamError) as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        print()
        return 130
    hint = "./run.sh steam login%s" % (
        "" if prefix == steam.default_prefix() else " --prefix %s" % prefix)
    if args.no_steam:
        print("setup done")
        return 0
    if args.no_login:
        print("setup done")
        return 0
    if not sys.stdin.isatty():
        print("setup done. Next, log in to Steam once: %s" % hint)
        return 0
    if steam.remembered(prefix):
        print("setup done. Steam has a saved login")
        return 0
    print("setup done. Now log in to the Steam client once")
    if do_login(prefix, login_mode(args)) != 0:
        print("Steam is not logged in yet. Try again with: %s" % hint)
    return 0


def cmd_steam(args):
    if launch.IS_WINDOWS:
        sys.exit("the steam command is for Linux. On Windows just start Steam and log in")
    prefix = steam.prefix_from(args.prefix)
    try:
        if args.action == "start":
            steam.start(prefix, show=args.show)
            return 0
        if args.action == "stop":
            steam.stop(prefix)
            return 0
        if args.action == "status":
            st = steam.status(prefix)
            print(steam.describe(st))
            return 0 if st["logged_in"] else 1
    except steam.SteamError as e:
        sys.exit(str(e))
    return do_login(prefix, login_mode(args), port=args.port, timeout=args.timeout)


def cmd_run(args):
    ac = ac_dir_from(args)
    check_build(ac)
    linux_steam(args)
    spec = spec_from_args(args, args.mode)
    out = out_dir_from(args, args.mode)
    try:
        results = drive.run(spec, ac, out)
    except (drive.RunError, launch.LaunchError) as e:
        sys.exit(str(e))
    drive.print_summary(results)
    print("results in %s" % out)
    if args.results:
        shutil.copyfile(os.path.join(out, "results.json"), args.results)
    return 0 if results["outcome"] == "ok" else 1


def cmd_test(args):
    ac = ac_dir_from(args)
    check_build(ac)
    linux_steam(args)
    out_root = out_dir_from(args, "test")
    reports = []
    for path in args.scenarios:
        try:
            sc = scenario.load(path)
        except (scenario.ScenarioError, drive.RunError, ValueError) as e:
            print("%s: %s" % (path, e))
            reports.append({"name": os.path.basename(path), "file": path, "seconds": 0,
                            "passed": False, "out": "",
                            "checks": [{"check": "load", "ok": False, "message": str(e)}]})
            continue
        print("== %s" % sc["name"])
        if args.memory_max:
            sc["run"].setdefault("memory_max", args.memory_max)
        rep = scenario.run_file(path, ac, out_root, overrides=sc["run"])
        for c in rep["checks"]:
            print("  %s %s: %s" % ("PASS" if c["ok"] else "FAIL", c["check"], c["message"]))
        reports.append(rep)
    os.makedirs(out_root, exist_ok=True)
    with open(os.path.join(out_root, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(reports, fh, indent=2)
    if args.junit:
        with open(args.junit, "w", encoding="utf-8") as fh:
            fh.write(scenario.junit(reports))
    passed = sum(1 for r in reports if r["passed"])
    print("%d of %d scenarios passed, report in %s" % (passed, len(reports), out_root))
    return 0 if passed == len(reports) else 1


def print_snapshot(snap):
    s = snap.get("session") or {}
    print("session %s laps=%s over=%s order=%s" % (s.get("type"), s.get("laps"), s.get("over"),
                                                   s.get("order")))
    for c in snap["cars"]:
        if not c:
            continue
        print("  car %-2d %s lap %-3d npos %.3f %6.1f km/h gear %d rpm %5.0f fuel %5.1f best %s%s" % (
            c["car"], "AI " if c["ai"] else "   ", c["laps"], c["npos"], c["speed_kmh"], c["gear"],
            c["rpm"], c["fuel"], state.fmt_ms(c["best_lap_ms"]), " pit" if c["in_pit"] else ""))


def cmd_probe(args):
    pids = [args.pid] if args.pid else memory.find_pids()
    if not pids:
        print("no acs.exe running")
        return 1
    pid = pids[0]
    if args.ac:
        version, _ = check_build(ac_dir_from(args))
    else:
        version = sorted(offsets.BUILDS)[0]
    reader = memory.open_process(pid)
    g = state.Game(reader, offsets.Offsets(version))
    try:
        while True:
            snap = g.snapshot()
            if args.json:
                print(json.dumps({"pid": pid, "state": snap}))
            elif snap:
                print("pid %d" % pid)
                print_snapshot(snap)
            else:
                print("pid %d: no session loaded" % pid)
            if not args.watch:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        reader.close()
    return 0


def add_run_args(p):
    p.add_argument("--track", required=True)
    p.add_argument("--layout", default="")
    p.add_argument("--car", required=True)
    p.add_argument("--ai", type=int, default=0, help="number of AI opponents")
    p.add_argument("--ai-car", action="append", help="opponent car, repeat for a mixed grid")
    p.add_argument("--ai-level", type=int, default=100)
    p.add_argument("--ai-aggression", type=int, default=0)
    p.add_argument("--laps", type=int, default=3)
    p.add_argument("--minutes", type=int, default=10, help="practice length")
    p.add_argument("--timeout", type=int, default=900, help="give up after this many seconds")
    p.add_argument("--render", choices=("off", "on"), default="off")
    p.add_argument("--no-drive", action="store_true", help="leave the player car parked")
    p.add_argument("--hz", type=int, default=10, help="telemetry samples per second")
    p.add_argument("--format", choices=("csv", "jsonl", "none"), default="csv")
    p.add_argument("--grip", type=int, default=100)
    p.add_argument("--weather", default="3_clear")
    p.add_argument("--ambient", type=int, default=22)
    p.add_argument("--road", type=int, default=28)
    p.add_argument("--memory-max", help="Linux only: cap the game, for example 3G")
    p.add_argument("--results", help="also copy results.json here")
    p.add_argument("--prefix", help="Linux only: Wine prefix with Steam")


def add_login_modes(p):
    m = p.add_mutually_exclusive_group()
    m.add_argument("--type", dest="mode", action="store_const", const="type",
                   help="login: ask in this terminal and type it into the hidden Steam window "
                        "(default without DISPLAY)")
    m.add_argument("--qr", dest="mode", action="store_const", const="qr",
                   help="login: show Steam's QR code here to scan with the Steam Mobile App")
    m.add_argument("--vnc", dest="mode", action="store_const", const="vnc",
                   help="login: show the window through VNC on localhost")
    m.add_argument("--window", dest="mode", action="store_const", const="window",
                   help="login: show the window on this desktop (default with DISPLAY)")


def parser():
    ap = argparse.ArgumentParser(prog="achl", description="Run Assetto Corsa headless.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("install", help="put the DLL and launcher into an AC folder")
    p.add_argument("--ac")
    p.add_argument("--from", dest="src", help="folder with achl.dll and achl_launch.exe")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("setup", help="Linux: Wine prefix, fonts, AC, unpacked acs.exe, Steam client")
    p.add_argument("--ac")
    p.add_argument("--install-ac", metavar="DIR",
                   help="download AC into DIR with steamcmd unless it is already there")
    p.add_argument("--steam-user", help="--install-ac: Steam account that owns AC")
    p.add_argument("--prefix", help="Wine prefix, default %s" % steam.default_prefix())
    p.add_argument("--no-steam", action="store_true", help="skip the Steam client")
    p.add_argument("--no-login", action="store_true", help="do not log in to Steam at the end")
    add_login_modes(p)
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("steam", help="Linux: start, stop, check or log in to Steam")
    p.add_argument("action", choices=("start", "stop", "status", "login"))
    p.add_argument("--prefix", help="Wine prefix, default %s" % steam.default_prefix())
    p.add_argument("--show", action="store_true", help="start: show Steam on this desktop")
    add_login_modes(p)
    p.add_argument("--port", type=int, help="login --vnc: port, default the first free from 5977")
    p.add_argument("--timeout", type=int, default=900, help="login: seconds to wait")
    p.set_defaults(func=cmd_steam)

    p = sub.add_parser("uninstall", help="remove what install added")
    p.add_argument("--ac")
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("run", help="run a session")
    p.add_argument("mode", choices=drive.MODES)
    p.add_argument("--ac")
    p.add_argument("--out", help="output folder")
    add_run_args(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("test", help="run JSON scenarios and check them")
    p.add_argument("scenarios", nargs="+")
    p.add_argument("--ac")
    p.add_argument("--out", help="output folder")
    p.add_argument("--junit", help="write a JUnit XML report here")
    p.add_argument("--memory-max", help="Linux only: cap the game, for example 3G")
    p.add_argument("--prefix", help="Linux only: Wine prefix with Steam")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("probe", help="show the state of a running game")
    p.add_argument("--ac")
    p.add_argument("--pid", type=int)
    p.add_argument("--watch", action="store_true")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_probe)
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    return args.func(args)
