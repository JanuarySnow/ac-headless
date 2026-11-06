import getpass
import json
import os
import re
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import time

FLAGS = ["-no-cef-sandbox", "-cef-disable-gpu", "-cef-disable-gpu-compositing"]
ACTIVE_KEY = r"HKCU\Software\Valve\Steam\ActiveProcess"
SUPERVISOR = 'while :; do "$@"; c=$?; [ "$c" = 42 ] || exit "$c"; done'


class SteamError(Exception):
    pass


def default_prefix():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local",
                                                           "share")
    return os.path.join(base, "ac-headless", "prefix")


def prefix_from(arg=None):
    p = arg or os.environ.get("WINEPREFIX") or default_prefix()
    return os.path.abspath(os.path.expanduser(p))


def wine():
    return os.environ.get("ACHL_WINE", "wine")


def steam_dir(prefix):
    return os.path.join(prefix, "drive_c", "Program Files (x86)", "Steam")


def has_file(folder, name):
    try:
        return any(n.lower() == name for n in os.listdir(folder)
                   if os.path.isfile(os.path.join(folder, n)))
    except OSError:
        return False


def installed(prefix):
    return has_file(steam_dir(prefix), "steam.exe")


def updated(prefix):
    return has_file(steam_dir(prefix), "steamclient64.dll")


def state_dir(prefix):
    d = os.path.join(prefix, "ac-headless")
    os.makedirs(d, exist_ok=True)
    return d


def read_state(prefix):
    try:
        with open(os.path.join(prefix, "ac-headless", "steam.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def write_state(prefix, data):
    with open(os.path.join(state_dir(prefix), "steam.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def clear_state(prefix):
    try:
        os.remove(os.path.join(prefix, "ac-headless", "steam.json"))
    except OSError:
        pass


def wine_env(prefix, display=None, xauth=None):
    env = dict(os.environ)
    env["WINEPREFIX"] = prefix
    env.setdefault("WINEDEBUG", "-all")
    if display:
        env["DISPLAY"] = display
        env.pop("XAUTHORITY", None)
    if xauth:
        env["XAUTHORITY"] = xauth
    return env


def _read_proc(pid, name):
    with open("/proc/%d/%s" % (pid, name), "rb") as fh:
        return [x.decode("utf-8", "replace") for x in fh.read().split(b"\0") if x]


def proc_env(pid):
    out = {}
    for item in _read_proc(pid, "environ"):
        k, _, v = item.partition("=")
        out[k] = v
    return out


def _same(a, b):
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except (OSError, ValueError):
        return False


def is_main(argv):
    return bool(argv) and re.split(r"[\\/]", argv[0])[-1].lower() == "steam.exe"


def is_steam(argv):
    return is_main(argv) or "\\steam\\" in " ".join(argv).lower()


def prefix_procs(prefix):
    found = []
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) == os.getpid():
            continue
        pid = int(name)
        try:
            env = proc_env(pid)
            argv = _read_proc(pid, "cmdline")
        except OSError:
            continue
        if env.get("WINEPREFIX") and _same(env["WINEPREFIX"], prefix):
            found.append((pid, argv, env))
    return found


def main_pids(prefix):
    return [p for p, argv, _ in prefix_procs(prefix) if is_main(argv)]


def steam_pids(prefix):
    return [p for p, argv, _ in prefix_procs(prefix) if is_steam(argv)]


def running_display(prefix):
    for pid, argv, env in prefix_procs(prefix):
        if is_main(argv):
            return pid, env.get("DISPLAY"), env.get("XAUTHORITY")
    return None, None, None


def parse_reg_query(text):
    m = re.search(r"ActiveUser\s+REG_DWORD\s+0x([0-9a-fA-F]+)", text)
    return int(m.group(1), 16) if m else None


def parse_user_reg(text):
    m = re.search(r"^\[Software\\\\Valve\\\\Steam\\\\ActiveProcess\][^\n]*\n(.*?)(?=^\[|\Z)",
                  text, re.S | re.M)
    if not m:
        return None
    v = re.search(r'^"ActiveUser"=dword:([0-9a-fA-F]{8})', m.group(1), re.M)
    return int(v.group(1), 16) if v else None


def remembered_text(text):
    return re.search(r'"RememberPassword"\s+"1"', text) is not None


def remembered(prefix):
    try:
        with open(os.path.join(steam_dir(prefix), "config", "loginusers.vdf"),
                  encoding="utf-8", errors="replace") as fh:
            return remembered_text(fh.read())
    except OSError:
        return False


def active_user(prefix, live=True):
    if live:
        try:
            r = subprocess.run([wine(), "reg", "query", ACTIVE_KEY, "/v", "ActiveUser"],
                               env=wine_env(prefix), stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=30)
            v = parse_reg_query(r.stdout)
            if v is not None:
                return v
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        with open(os.path.join(prefix, "user.reg"), encoding="utf-8", errors="replace") as fh:
            return parse_user_reg(fh.read())
    except OSError:
        return None


def status(prefix):
    pid, display, _ = running_display(prefix)
    st = {"prefix": prefix, "installed": installed(prefix), "running": pid is not None,
          "pid": pid, "display": display, "remembered": remembered(prefix), "logged_in": False}
    if pid is not None:
        st["logged_in"] = bool(active_user(prefix))
    return st


def describe(st):
    if not st["installed"]:
        return "Steam is not installed in %s. Run install.sh first" % st["prefix"]
    if not st["running"]:
        return "Steam is not running (prefix %s, %s)" % (
            st["prefix"], "a login is remembered" if st["remembered"] else "no login remembered")
    return "Steam is running (pid %d, display %s) and %s" % (
        st["pid"], st["display"], "logged in" if st["logged_in"] else "not logged in")


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def _argv(pid):
    try:
        return _read_proc(pid, "cmdline")
    except (OSError, TypeError):
        return []


def free_display():
    for n in range(90, 200):
        if not os.path.exists("/tmp/.X11-unix/X%d" % n) and not os.path.exists("/tmp/.X%d-lock" % n):
            return n
    raise SteamError("no free X display number for Xvfb")


def xauth_entry(cookie):
    name = b"MIT-MAGIC-COOKIE-1"
    return (struct.pack(">HH", 0xFFFF, 0) + struct.pack(">H", 0) + struct.pack(">H", len(name))
            + name + struct.pack(">H", len(cookie)) + cookie)


class Display:
    def __init__(self, folder, size="1280x800x24"):
        self.folder = folder
        self.size = size
        self.number = None
        self.proc = None
        self.xauth = None

    @property
    def name(self):
        return ":%d" % self.number

    def start(self, detach=False):
        if shutil.which("Xvfb") is None:
            raise SteamError("Xvfb is not installed")
        os.makedirs(self.folder, exist_ok=True)
        self.number = free_display()
        self.xauth = os.path.join(self.folder, "xauth-%d" % self.number)
        fd = os.open(self.xauth, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(xauth_entry(secrets.token_bytes(16)))
        self.proc = subprocess.Popen(
            ["Xvfb", self.name, "-nolisten", "tcp", "-auth", self.xauth, "-screen", "0", self.size],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=detach)
        for _ in range(100):
            if os.path.exists("/tmp/.X11-unix/X%d" % self.number):
                return self
            if self.proc.poll() is not None:
                break
            time.sleep(0.1)
        raise SteamError("Xvfb did not start on %s" % self.name)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.xauth:
            try:
                os.remove(self.xauth)
            except OSError:
                pass


def start(prefix, show=False, log=print):
    if not installed(prefix):
        raise SteamError("Steam is not installed in %s. Run install.sh first" % prefix)
    pid, display, _ = running_display(prefix)
    if pid:
        log("Steam is already running (pid %d, display %s)" % (pid, display))
        return pid
    sd = state_dir(prefix)
    xvfb_pid = xauth = None
    if show:
        display = os.environ.get("DISPLAY")
        if not display:
            raise SteamError("--show needs a desktop (DISPLAY is not set)")
    else:
        d = Display(sd).start(detach=True)
        display, xauth, xvfb_pid = d.name, d.xauth, d.proc.pid
    env = wine_env(prefix, display, xauth or os.environ.get("XAUTHORITY"))
    with open(os.path.join(sd, "steam.log"), "ab") as logf:
        sup = subprocess.Popen(["sh", "-c", SUPERVISOR, "achl-steam", wine(), "steam.exe"] + FLAGS,
                               cwd=steam_dir(prefix), env=env, stdin=subprocess.DEVNULL,
                               stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
    write_state(prefix, {"supervisor": sup.pid, "xvfb": xvfb_pid, "display": display,
                         "xauth": xauth})
    deadline = time.time() + 120
    while time.time() < deadline:
        pids = main_pids(prefix)
        if pids:
            log("started Steam (pid %d, display %s)" % (pids[0], display))
            return pids[0]
        if sup.poll() is not None:
            break
        time.sleep(0.5)
    code = sup.poll()
    stop(prefix, log=lambda m: None)
    raise SteamError("Steam did not start (%s), see %s" % (
        "exit code %s" % code if code is not None else "timeout",
        os.path.join(sd, "steam.log")))


def stop(prefix, log=print, wait=30):
    st = read_state(prefix)
    sup = st.get("supervisor")
    if sup and _alive(sup) and "achl-steam" in _argv(sup):
        os.kill(sup, signal.SIGTERM)
    pid, display, xauth = running_display(prefix)
    if pid:
        try:
            subprocess.run([wine(), "steam.exe", "-shutdown"], cwd=steam_dir(prefix),
                           env=wine_env(prefix, display, xauth), stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=wait)
        except (OSError, subprocess.TimeoutExpired):
            pass
        deadline = time.time() + wait
        while time.time() < deadline and steam_pids(prefix):
            time.sleep(1)
    left = steam_pids(prefix)
    for p in left:
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass
    xpid = st.get("xvfb")
    if xpid and _alive(xpid) and _argv(xpid)[:2] == ["Xvfb", st.get("display")]:
        os.kill(xpid, signal.SIGTERM)
    if st.get("xauth"):
        try:
            os.remove(st["xauth"])
        except OSError:
            pass
    clear_state(prefix)
    if pid or left:
        log("stopped Steam%s" % (" (killed %d leftover processes)" % len(left) if left else ""))
    else:
        log("Steam was not running")


def wait_logged_in(prefix, timeout, poll=3.0):
    deadline = time.time() + timeout
    gone = 0
    while time.time() < deadline:
        if main_pids(prefix):
            gone = 0
            if active_user(prefix):
                return True
        else:
            gone += 1
            if gone * poll >= 20:
                raise SteamError("Steam exited, see %s" % os.path.join(prefix, "ac-headless",
                                                                        "steam.log"))
        time.sleep(poll)
    return False


def ensure_ready(prefix, log=print, wait=120):
    if os.environ.get("ACHL_STEAM") == "off":
        return
    if not installed(prefix):
        raise SteamError("Steam is not installed in %s. Run ./install.sh /path/to/assettocorsa "
                         "first, or pass --prefix" % prefix)
    if not main_pids(prefix):
        if not remembered(prefix):
            raise SteamError("Steam has no saved login in %s. Run: ./run.sh steam login" % prefix)
        start(prefix, log=log)
    if active_user(prefix):
        return
    if not remembered(prefix):
        raise SteamError("Steam is running but not logged in. Run: ./run.sh steam login")
    log("waiting for Steam to log in")
    if not wait_logged_in(prefix, wait):
        raise SteamError("Steam is running but not logged in. Run: ./run.sh steam login")


def free_port(start=5977):
    for port in range(start, start + 100):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    raise SteamError("no free port for VNC")


def _listening(port):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_vnc(prefix, display, xauth, port):
    if shutil.which("x11vnc") is None:
        raise SteamError("x11vnc is not installed")
    password = secrets.token_hex(4)
    pwfile = os.path.join(state_dir(prefix), "vnc-pass")
    fd = os.open(pwfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(password + "\n")
    env = dict(os.environ)
    env.pop("XAUTHORITY", None)
    if xauth:
        env["XAUTHORITY"] = xauth
    logf = open(os.path.join(state_dir(prefix), "vnc.log"), "ab")
    proc = subprocess.Popen(["x11vnc", "-display", display, "-localhost", "-rfbport", str(port),
                             "-forever", "-shared", "-passwdfile", "rm:" + pwfile],
                            env=env, stdin=subprocess.DEVNULL, stdout=logf,
                            stderr=subprocess.STDOUT)
    logf.close()
    for _ in range(100):
        if _listening(port):
            return proc, password
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    if proc.poll() is None:
        proc.kill()
    try:
        os.remove(pwfile)
    except OSError:
        pass
    raise SteamError("x11vnc did not start, see %s" % os.path.join(state_dir(prefix), "vnc.log"))


def ssh_hint(port):
    return "ssh -N -L %d:localhost:%d %s@%s" % (port, port, getpass.getuser(), socket.gethostname())


def _xdo(env, *args, data=None, timeout=60):
    return subprocess.run(["xdotool"] + list(args), env=env, input=data, text=True,
                          capture_output=True, timeout=timeout)


def find_login_window(env, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _xdo(env, "search", "--onlyvisible", "--name", "Steam")
        best = None
        for wid in r.stdout.split():
            g = _xdo(env, "getwindowgeometry", "--shell", wid).stdout
            m = dict(re.findall(r"(\w+)=(\d+)", g))
            area = int(m.get("WIDTH", 0)) * int(m.get("HEIGHT", 0))
            if area > 100000 and (best is None or area > best[0]):
                best = (area, wid)
        if best:
            return best[1]
        time.sleep(2)
    raise SteamError("the Steam login window did not appear")


def type_text(env, wid, text):
    _xdo(env, "windowfocus", "--sync", wid)
    r = _xdo(env, "type", "--delay", "60", "--file", "-", data=text, timeout=120)
    if r.returncode != 0:
        raise SteamError("xdotool could not type into the Steam window")


def vnc_login(prefix, display, xauth, port, timeout, log=print):
    port = port or free_port()
    vnc, password = start_vnc(prefix, display, xauth, port)
    try:
        log("Steam's login window is on a VNC server that only listens on this machine.")
        log("From your own computer, open a tunnel:")
        log("    " + ssh_hint(port))
        log("That window prints nothing while the tunnel is open. Leave it running.")
        log("Then point a VNC viewer at localhost:%d and use the password %s" % (port, password))
        log("If you are on this machine already, use localhost:%d directly." % port)
        log("Log in and tick Remember me. Waiting up to %ds, Ctrl+C to give up." % timeout)
        return wait_logged_in(prefix, timeout)
    finally:
        vnc.terminate()
        try:
            vnc.wait(5)
        except subprocess.TimeoutExpired:
            vnc.kill()
        log("VNC server stopped")
