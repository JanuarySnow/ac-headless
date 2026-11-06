import os
import select
import shutil
import signal
import subprocess
import sys
import time

try:
    import termios
except ImportError:
    termios = None

from . import screen, steam

TRIES = 3


class PromptTimeout(steam.SteamError):
    pass


class Terminal:
    def __init__(self, fd=None, out=None):
        self.fd = sys.stdin.fileno() if fd is None else fd
        self.out = out or sys.stdout
        if not os.isatty(self.fd):
            raise steam.SteamError("this login asks questions in the terminal, and there is none. "
                                   "Run it from a terminal, or use --qr or --vnc")

    def ask(self, text, secret=False, timeout=300, done=None):
        old = termios.tcgetattr(self.fd)
        if secret:
            new = termios.tcgetattr(self.fd)
            new[3] &= ~termios.ECHO
            termios.tcsetattr(self.fd, termios.TCSADRAIN, new)
        self.out.write(text)
        self.out.flush()
        buf = b""
        deadline = time.time() + timeout
        try:
            while b"\n" not in buf and b"\r" not in buf:
                left = deadline - time.time()
                if left <= 0:
                    raise PromptTimeout("no answer in the terminal within %ds" % timeout)
                r, _, _ = select.select([self.fd], [], [], min(left, 2.0))
                if r:
                    chunk = os.read(self.fd, 4096)
                    if not chunk:
                        raise steam.SteamError("the terminal was closed")
                    buf += chunk
                elif done is not None and done():
                    if not secret:
                        self.out.write("\n")
                    return None
        finally:
            if secret:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, old)
                self.out.write("\n")
                self.out.flush()
        return buf.replace(b"\r", b"\n").split(b"\n")[0].decode("utf-8", "replace")


class Watch:
    def __init__(self, prefix, display, xauth):
        self.prefix = prefix
        self.display = display
        self.xauth = xauth
        self.log = os.path.join(steam.steam_dir(prefix), "logs", "steamui_login.txt")
        self.offset = self._size()
        self.polls = 0

    def _size(self):
        try:
            return os.path.getsize(self.log)
        except OSError:
            return 0

    def log_success(self):
        size = self._size()
        if size < self.offset:
            self.offset = 0
        if size == self.offset:
            return False
        try:
            with open(self.log, "rb") as fh:
                fh.seek(self.offset)
                text = fh.read().decode("utf-8", "replace")
        except OSError:
            return False
        return "SetLoginState: Success" in text

    def logged_in(self):
        if not steam.main_pids(self.prefix):
            raise steam.SteamError("Steam exited during the login, see %s" % os.path.join(
                self.prefix, "ac-headless", "steam.log"))
        if self.log_success():
            return True
        self.polls += 1
        return self.polls % 3 == 0 and bool(steam.active_user(self.prefix))

    def look(self):
        try:
            img = screen.capture(self.display, self.xauth)
        except screen.ScreenError:
            return {"error": False, "form": False}, None
        return screen.look(img), img


def classify(states):
    if any(s == "ok" for s in states):
        return "ok"
    return states[-1] if len(states) >= 2 and states[-1] == states[-2] else None


def outcome(watch, seconds, guard_after=8.0, poll=1.5, sleep=time.sleep, stale=False):
    start = time.time()
    seen_clear = not stale
    states = []
    img = None
    while time.time() - start < seconds:
        sleep(poll)
        if watch.logged_in():
            return "ok", None
        st, img = watch.look()
        if not st["error"]:
            seen_clear = True
        if st["error"]:
            states.append("error" if seen_clear or time.time() - start > 5 else "stale")
        elif st["form"]:
            states.append("form")
        else:
            states.append("other")
        c = classify(states)
        if c == "error":
            return "error", img
        if c == "other" and time.time() - start >= guard_after:
            return "guard", img
    return "timeout", img


def xdo_env(display, xauth):
    env = dict(os.environ)
    env["DISPLAY"] = display
    env.pop("XAUTHORITY", None)
    if xauth:
        env["XAUTHORITY"] = xauth
    return env


def wait_form(watch, seconds, sleep=time.sleep):
    deadline = time.time() + seconds
    while time.time() < deadline:
        st, _ = watch.look()
        if st["form"]:
            return True
        sleep(1)
    return False


def fill_form(env, wid, user, password, img=None):
    fields = screen.red_fields(img) if img is not None else []
    if img is not None and len(fields) < 2:
        raise steam.SteamError("could not find the login fields again. Run the login once more")
    if fields:
        for (x, y), text in zip(fields[:2], (user, password)):
            steam._xdo(env, "mousemove", "--sync", str(x), str(y), "click", "1")
            steam._xdo(env, "key", "ctrl+a")
            steam.type_text(env, wid, text)
    else:
        steam.type_text(env, wid, user)
        steam._xdo(env, "key", "Tab")
        steam.type_text(env, wid, password)
    steam._xdo(env, "key", "Return")


def type_login(prefix, display, xauth, deadline, term, log=print):
    if shutil.which("xdotool") is None:
        raise steam.SteamError("this login needs xdotool. Install it, or use --qr or --vnc")
    env = xdo_env(display, xauth)
    watch = Watch(prefix, display, xauth)
    left = lambda: max(1, int(deadline - time.time()))
    log("waiting for the Steam login window")
    wid = steam.find_login_window(env, timeout=min(180, left()))
    if not wait_form(watch, min(90, left())):
        raise steam.SteamError("the Steam login window did not finish loading")
    img = None
    for attempt in range(TRIES):
        user = term.ask("Steam account name: ", timeout=left()).strip()
        password = term.ask("Steam password: ", secret=True, timeout=left())
        if not user or not password:
            raise steam.SteamError("account name and password are needed")
        fill_form(env, wid, user, password, img)
        password = None
        log("signing in")
        result, img = outcome(watch, min(90, left()), stale=img is not None)
        if result == "ok":
            return True
        if result == "guard":
            return guard(watch, env, wid, deadline, term, log)
        if result == "timeout":
            raise steam.SteamError("Steam did not answer the sign in")
        log("Steam says the account name or password is wrong")
    raise steam.SteamError("wrong account name or password %d times, stopping" % TRIES)


def guard(watch, env, wid, deadline, term, log=print):
    left = lambda: max(1, int(deadline - time.time()))
    log("Steam wants Steam Guard. Approve the sign in in the Steam Mobile App, or type the code "
        "from the email or the app here.")
    wrong = 0
    while True:
        code = term.ask("Steam Guard code (or approve in the app and wait): ", timeout=left(),
                        done=watch.logged_in)
        if code is None:
            return True
        code = code.strip()
        if not code:
            continue
        steam._xdo(env, "windowfocus", "--sync", wid)
        steam._xdo(env, "key", "--repeat", "8", "BackSpace")
        steam.type_text(env, wid, code)
        steam._xdo(env, "key", "Return")
        result, _ = outcome(watch, min(45, left()), guard_after=1e9, stale=wrong > 0)
        if result == "ok":
            return True
        if result == "error":
            wrong += 1
            if wrong >= TRIES:
                raise steam.SteamError("wrong Steam Guard code %d times, stopping" % TRIES)
            log("Steam says that code is wrong. Use the newest code")
            continue
        log("Steam has not finished signing in yet. If the Steam app asks you to approve, do that")


def qr_login(prefix, display, xauth, deadline, log=print, out=None):
    out = out or sys.stdout
    watch = Watch(prefix, display, xauth)
    log("waiting for the Steam login window")
    if not wait_form(watch, min(180, max(1, deadline - time.time()))):
        raise steam.SteamError("the Steam login window did not finish loading")
    last = None
    while time.time() < deadline:
        if watch.logged_in():
            return True
        try:
            m = screen.qr_matrix(screen.capture(display, xauth))
        except screen.ScreenError:
            m = None
        if m and m != last:
            out.write("\nOpen the Steam Mobile App, tap the shield, Scan a QR code, and scan "
                      "this:\n\n%s\n\n" % screen.qr_text(m))
            out.flush()
            last = m
        time.sleep(2)
    return False


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def run(prefix, mode, port=None, timeout=900, log=print, term=None):
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, _interrupt)
    if not steam.installed(prefix):
        raise steam.SteamError("Steam is not installed in %s. Run install.sh first" % prefix)
    deadline = time.time() + timeout
    pid, display, xauth = steam.running_display(prefix)
    if pid and steam.active_user(prefix):
        log("Steam is already logged in")
        return True
    if mode == "type" and term is None and not steam.remembered(prefix):
        term = Terminal()
    started = False
    if mode == "window" and pid and display != os.environ.get("DISPLAY"):
        steam.stop(prefix, log=log)
        pid = None
    if not pid:
        steam.start(prefix, show=mode == "window", log=log)
        started = True
        pid, display, xauth = steam.running_display(prefix)
    ok = False
    try:
        if steam.remembered(prefix):
            log("Steam has a saved login, waiting for it")
            if steam.wait_logged_in(prefix, min(90, timeout)):
                ok = True
                return ok
            log("the saved login did not work")
        if mode == "window":
            log("log in in the Steam window and tick Remember me. Waiting up to %ds" % timeout)
            ok = steam.wait_logged_in(prefix, timeout)
        elif mode == "type":
            ok = type_login(prefix, display, xauth, deadline, term or Terminal(), log)
        elif mode == "qr":
            ok = qr_login(prefix, display, xauth, deadline, log)
        else:
            ok = steam.vnc_login(prefix, display, xauth, port, timeout, log)
        return ok
    finally:
        if not ok and started:
            steam.stop(prefix, log=log)
