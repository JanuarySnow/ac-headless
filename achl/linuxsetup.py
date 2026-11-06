import os
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

from . import offsets, steam

STEAMLESS_VERSION = "3.1.0.5"
STEAMLESS_URL = ("https://github.com/atom0s/Steamless/releases/download/v%s/"
                 "Steamless.v%s.-.by.atom0s.zip" % (STEAMLESS_VERSION, STEAMLESS_VERSION))
STEAM_SETUP_URL = "https://cdn.cloudflare.steamstatic.com/client/installer/SteamSetup.exe"
STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
AC_APP = 244210
AC_GB = 20
FONTS = ("arial.ttf", "tahoma.ttf")
VERBS = ("corefonts", "tahoma", "dxvk", "d3dx11_43", "d3dcompiler_43", "d3dcompiler_47")


class SetupError(Exception):
    pass


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    d = os.path.join(base, "ac-headless")
    os.makedirs(d, exist_ok=True)
    return d


def download(url, dest, log=print):
    if os.path.isfile(dest):
        return dest
    log("downloading %s" % url)
    part = dest + ".part"
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as fh:
            shutil.copyfileobj(r, fh, 1 << 20)
    except OSError as e:
        raise SetupError("download failed: %s (%s)" % (url, e))
    os.replace(part, dest)
    return dest


def need(*tools):
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        raise SetupError("missing programs: %s. install.sh can install them" % ", ".join(missing))


def run(args, env, timeout, cwd=None, what=None):
    try:
        return subprocess.run(args, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        raise SetupError("%s took longer than %ds" % (what or args[0], timeout))


def make_prefix(prefix, env, log=print):
    if os.path.isfile(os.path.join(prefix, "system.reg")):
        log("Wine prefix: %s (exists)" % prefix)
        return
    log("Wine prefix: creating %s" % prefix)
    os.makedirs(prefix, exist_ok=True)
    e = dict(env)
    e["WINEDLLOVERRIDES"] = "mscoree,mshtml="
    run([steam.wine(), "wineboot", "-i"], e, 600, what="wineboot")
    wait_idle(prefix, 300)
    if not os.path.isfile(os.path.join(prefix, "system.reg")):
        raise SetupError("wineboot did not create the prefix")


def wait_idle(prefix, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not steam.prefix_procs(prefix):
            return
        time.sleep(1)
    raise SetupError("Wine processes in %s did not exit within %ds" % (prefix, timeout))


def winetricks_done(prefix):
    try:
        with open(os.path.join(prefix, "winetricks.log"), encoding="utf-8", errors="replace") as fh:
            return {l.strip() for l in fh if l.strip()}
    except OSError:
        return set()


def has_fonts(prefix):
    try:
        names = {n.lower() for n in os.listdir(os.path.join(prefix, "drive_c", "windows", "Fonts"))}
    except OSError:
        return False
    return all(f in names for f in FONTS)


def install_verbs(prefix, env, log=print):
    todo = [v for v in VERBS if v not in winetricks_done(prefix)]
    if not todo:
        log("fonts and Direct3D libraries: present")
        return
    need("winetricks", "cabextract")
    log("fonts and Direct3D libraries: installing %s with winetricks" % " ".join(todo))
    code = run(["winetricks", "-q"] + todo, env, 2400, what="winetricks")
    wait_idle(prefix, 300)
    left = [v for v in todo if v not in winetricks_done(prefix)]
    if left or not has_fonts(prefix):
        raise SetupError("winetricks exited with %s and did not install %s" % (
            code, " ".join(left) or "the fonts"))


def steamless_dir(log=print):
    d = os.path.join(cache_dir(), "steamless-" + STEAMLESS_VERSION)
    cli = os.path.join(d, "Steamless.CLI.exe")
    if os.path.isfile(cli):
        return d
    z = download(STEAMLESS_URL, os.path.join(cache_dir(), "steamless-%s.zip" % STEAMLESS_VERSION),
                 log)
    os.makedirs(d, exist_ok=True)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(d)
    if not os.path.isfile(cli):
        raise SetupError("Steamless.CLI.exe not found in %s" % z)
    return d


def needs_unpack(ac):
    try:
        return offsets.identify(os.path.join(ac, "acs.exe"))[1] == "steam"
    except (OSError, offsets.UnknownBuild):
        return False


def unpack(ac, log=print):
    exe = os.path.join(ac, "acs.exe")
    try:
        version, kind = offsets.identify(exe)
    except offsets.UnknownBuild as e:
        raise SetupError(str(e))
    if kind != "steam":
        log("acs.exe: already unpacked (AC %s, %s)" % (version, kind))
        return
    need("mono")
    tool = steamless_dir(log)
    out = exe + ".unpacked.exe"
    if os.path.exists(out):
        os.remove(out)
    log("acs.exe: removing Steam's DRM wrapper with Steamless %s" % STEAMLESS_VERSION)
    env = dict(os.environ)
    env["MONO_PATH"] = os.path.join(tool, "Plugins")
    code = run(["mono", os.path.join(tool, "Steamless.CLI.exe"), exe], env, 600, cwd=tool,
               what="Steamless")
    if not os.path.isfile(out):
        raise SetupError("Steamless did not write %s (exit code %s)" % (out, code))
    try:
        v2, k2 = offsets.identify(out)
    except offsets.UnknownBuild as e:
        os.remove(out)
        raise SetupError("the unpacked exe failed the build check: %s" % e)
    if k2 == "steam":
        os.remove(out)
        raise SetupError("the unpacked exe still looks like the DRM build")
    backup = exe + ".steam"
    if not os.path.exists(backup):
        shutil.copy2(exe, backup)
    os.replace(out, exe)
    log("acs.exe: unpacked (AC %s, %s). The original is kept as acs.exe.steam" % (v2, k2))


def install_steam(prefix, env, log=print):
    sdir = steam.steam_dir(prefix)
    if not steam.installed(prefix):
        setup = download(STEAM_SETUP_URL, os.path.join(cache_dir(), "SteamSetup.exe"), log)
        log("Steam client: installing into the prefix")
        run([steam.wine(), setup, "/S"], env, 900, what="SteamSetup.exe")
        wait_idle(prefix, 120)
        if not steam.installed(prefix):
            raise SetupError("SteamSetup.exe did not install steam.exe")
    if steam.updated(prefix):
        log("Steam client: installed")
        return
    log("Steam client: first start, Steam downloads its update now (a few hundred MB)")
    code = first_start(prefix, env, sdir)
    if code == 42:
        log("Steam client: updated itself and exited with code 42, as expected")
    for p in steam.steam_pids(prefix):
        try:
            os.kill(p, 9)
        except OSError:
            pass
    wait_idle(prefix, 120)
    if not steam.updated(prefix):
        raise SetupError("Steam did not finish updating (exit code %s), see %s" % (
            code, os.path.join(steam.state_dir(prefix), "steam.log")))
    log("Steam client: installed")


def webhelper_up(prefix):
    return any("steamwebhelper" in " ".join(argv).lower()
               for _, argv, _ in steam.prefix_procs(prefix))


def first_start(prefix, env, sdir, timeout=1800):
    with open(os.path.join(steam.state_dir(prefix), "steam.log"), "ab") as logf:
        proc = subprocess.Popen([steam.wine(), "steam.exe"] + steam.FLAGS, cwd=sdir, env=env,
                                stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT)
    deadline = time.time() + timeout
    seen = 0
    while time.time() < deadline:
        code = proc.poll()
        if code is not None:
            return code
        if steam.updated(prefix) and webhelper_up(prefix):
            seen += 1
            if seen >= 10:
                return "running"
        time.sleep(2)
    proc.kill()
    raise SetupError("Steam's first start took longer than %ds" % timeout)


def data_dir():
    return os.path.dirname(steam.default_prefix())


def steamcmd_dir():
    return os.path.join(data_dir(), "steamcmd")


def extract_tar(path, dest):
    with tarfile.open(path) as tf:
        for m in tf.getmembers():
            target = os.path.realpath(os.path.join(dest, m.name))
            if not target.startswith(os.path.realpath(dest) + os.sep) or m.issym() or m.islnk():
                raise SetupError("unexpected file in %s: %s" % (path, m.name))
        tf.extractall(dest)


def get_steamcmd(log=print):
    d = steamcmd_dir()
    sh = os.path.join(d, "steamcmd.sh")
    if os.path.isfile(sh):
        return d
    tgz = download(STEAMCMD_URL, os.path.join(cache_dir(), "steamcmd_linux.tar.gz"), log)
    os.makedirs(d, exist_ok=True)
    extract_tar(tgz, d)
    if not os.path.isfile(sh):
        raise SetupError("steamcmd.sh not found in %s" % tgz)
    return d


def steamcmd_args(folder, user, app=AC_APP):
    return ["+@sSteamCmdForcePlatformType", "windows", "+force_install_dir", folder,
            "+login", user, "+app_update", str(app), "validate", "+quit"]


def ac_version(folder):
    try:
        return offsets.identify(os.path.join(folder, "acs.exe"))[0]
    except (OSError, offsets.UnknownBuild):
        return None


def children(pid):
    kids = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % name, encoding="utf-8", errors="replace") as fh:
                ppid = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == pid:
            kids.append(int(name))
    return kids


def kill_tree(pid, sig=signal.SIGTERM):
    for kid in children(pid):
        kill_tree(kid, sig)
    try:
        os.kill(pid, sig)
    except OSError:
        pass


def run_steamcmd(args, log=print, timeout=None):
    d = get_steamcmd(log)
    home = os.path.join(d, "home")
    os.makedirs(home, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = home
    proc = subprocess.Popen([os.path.join(d, "steamcmd.sh")] + args, cwd=d, env=env)
    try:
        return proc.wait(timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc.pid)
        raise SetupError("steamcmd took longer than %ds" % timeout)
    except BaseException:
        kill_tree(proc.pid)
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid, signal.SIGKILL)
        raise


def install_ac(folder, user=None, log=print, read=input, app=AC_APP, need_gb=AC_GB,
               check=ac_version):
    found = check(folder)
    if found:
        log("Assetto Corsa: already in %s (AC %s)" % (folder, found))
        return
    if os.path.exists(os.path.join(folder, "acs.exe")):
        raise SetupError("%s has an acs.exe this tool does not know. Use an empty folder for "
                         "--install-ac" % folder)
    os.makedirs(folder, exist_ok=True)
    free = shutil.disk_usage(folder).free / float(1 << 30)
    if free < need_gb:
        raise SetupError("only %.0f GB free in %s, AC needs about %d GB" % (free, folder, need_gb))
    if not user:
        if not sys.stdin.isatty():
            raise SetupError("say which Steam account owns AC with --steam-user")
        user = read("Steam account that owns Assetto Corsa: ").strip()
        if not user:
            raise SetupError("no Steam account given")
    log("Assetto Corsa: downloading into %s with steamcmd. steamcmd asks for the password and "
        "the Steam Guard code itself, and remembers the login for next time" % folder)
    code = run_steamcmd(steamcmd_args(folder, user, app), log)
    found = check(folder)
    if not found:
        raise SetupError("steamcmd exited with code %s and %s has no usable acs.exe. Its "
                         "messages are above" % (code, folder))
    log("Assetto Corsa: installed in %s (AC %s)" % (folder, found))


def setup(ac, prefix, with_steam=True, get_ac=False, steam_user=None, log=print):
    need(steam.wine(), "Xvfb")
    drm = bool(ac) and (get_ac or needs_unpack(ac))
    if drm:
        need("mono")
    display = steam.Display(os.path.join(cache_dir(), "x"), "1024x768x24").start()
    try:
        env = steam.wine_env(prefix, display.name, display.xauth)
        make_prefix(prefix, env, log)
        install_verbs(prefix, env, log)
        if drm:
            steamless_dir(log)
        if get_ac:
            install_ac(ac, steam_user, log)
        if ac:
            unpack(ac, log)
        if with_steam:
            install_steam(prefix, env, log)
    finally:
        display.stop()
