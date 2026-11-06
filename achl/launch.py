import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from . import memory

IS_WINDOWS = sys.platform == "win32"
INSTALL_DIR = "achl"
DLL = "achl.dll"
LAUNCHER = "achl_launch.exe"

HEADLESS_WINDOWS = {"ACHL_WARP": "1", "ACHL_FAKESWAP": "1", "ACHL_TEXSHRINK": "1",
                    "ACHL_BUFSHRINK": "1", "ACHL_HIDEWIN": "1", "ACHL_NOAUDIO": "1",
                    "ACHL_NOINPUT": "1", "ACHL_SLEEP0_MS": "1", "ACHL_RENDER_OFF": "1"}
HEADLESS_WINE = {"ACHL_NOAUDIO": "1", "ACHL_NOINPUT": "1", "ACHL_RENDER_OFF": "1"}
VISIBLE = {"ACHL_NOINPUT": "1"}


class LaunchError(Exception):
    pass


def to_windows_path(path):
    path = os.path.abspath(path)
    if IS_WINDOWS:
        return path
    return "Z:" + path.replace("/", "\\")


def installed_files(ac_dir):
    d = os.path.join(ac_dir, INSTALL_DIR)
    return os.path.join(d, DLL), os.path.join(d, LAUNCHER)


def dll_env(render, offsets, docs_root, log_path, drive=False, start_race=False,
            start_delay_ms=3000, wait_s=300):
    if render == "on":
        env = dict(VISIBLE)
    else:
        env = dict(HEADLESS_WINDOWS if IS_WINDOWS else HEADLESS_WINE)
    env["ACHL_DOCS"] = to_windows_path(docs_root)
    env["ACHL_LOG"] = to_windows_path(log_path)
    env["ACHL_OFFSETS"] = offsets.dll_env()
    env["ACHL_WAIT_S"] = str(int(wait_s))
    env["ACHL_START_DELAY_MS"] = str(int(start_delay_ms))
    if drive:
        env["ACHL_AUTODRIVE"] = "1"
    if start_race:
        env["ACHL_AUTOSTART"] = "1"
    for k, v in os.environ.items():
        if k.startswith("ACHL_") and k not in ("ACHL_AC", "ACHL_OFFSETS", "ACHL_RUN_ID",
                                               "ACHL_PTRACER"):
            env[k] = v
    return env


def _free_display():
    for n in range(90, 120):
        if not os.path.exists("/tmp/.X11-unix/X%d" % n) and not os.path.exists("/tmp/.X%d-lock" % n):
            return n
    raise LaunchError("no free X display number for Xvfb")


def memory_cap(memory_max, log=None):
    if not memory_max:
        return []
    log = log or (lambda m: print(m, file=sys.stderr))
    if shutil.which("systemd-run") is None:
        log("--memory-max ignored: systemd-run not found. Running without a memory cap")
        return []
    cap = ["systemd-run", "--user", "--scope", "-q", "-p", "MemoryMax=%s" % memory_max]
    try:
        ok = subprocess.run(cap + ["true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if not ok:
        log("--memory-max ignored: systemd-run --user cannot reach a user session bus, which is "
            "normal over sudo or su. Log in as this user directly, or run "
            "'loginctl enable-linger' once. Running without a memory cap")
        return []
    return cap


class Game:
    def __init__(self, ac_dir, env, out_dir, memory_max=None, wine=None, prefix=None):
        self.ac_dir = os.path.abspath(ac_dir)
        self.env = env
        self.out_dir = out_dir
        self.memory_max = memory_max
        self.wine = wine or os.environ.get("ACHL_WINE", "wine")
        self.prefix = prefix or os.environ.get("WINEPREFIX")
        self.proc = None
        self.xvfb = None
        self.pid = None
        self.lines = []
        self.run_id = uuid.uuid4().hex

    def start(self):
        dll, launcher = installed_files(self.ac_dir)
        exe = os.path.join(self.ac_dir, "acs.exe")
        for p in (dll, launcher, exe):
            if not os.path.isfile(p):
                raise LaunchError("missing %s (run install first)" % p)
        env = dict(os.environ)
        env.update(self.env)
        env["ACHL_RUN_ID"] = self.run_id
        args = [launcher, to_windows_path(dll), to_windows_path(exe), to_windows_path(self.ac_dir)]
        flags = 0
        if IS_WINDOWS:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            if shutil.which(self.wine) is None:
                raise LaunchError("wine not found (set ACHL_WINE)")
            args = [self.wine, to_windows_path(launcher)] + args[1:]
            if self.prefix:
                env["WINEPREFIX"] = self.prefix
            env.setdefault("WINEDEBUG", "-all")
            env["ACHL_PTRACER"] = str(os.getpid())
            if not env.get("DISPLAY"):
                env["DISPLAY"] = self._start_xvfb()
            args = memory_cap(self.memory_max) + args
        log = open(os.path.join(self.out_dir, "launcher.log"), "w")
        self.proc = subprocess.Popen(args, cwd=self.ac_dir, env=env, stdout=subprocess.PIPE,
                                     stderr=log, text=True, creationflags=flags)
        threading.Thread(target=self._pump, daemon=True).start()
        return self

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.append(line.strip())

    def _start_xvfb(self):
        if shutil.which("Xvfb") is None:
            raise LaunchError("no DISPLAY and Xvfb is not installed")
        n = _free_display()
        self.xvfb = subprocess.Popen(["Xvfb", ":%d" % n, "-ac", "-screen", "0", "1024x768x24"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if os.path.exists("/tmp/.X11-unix/X%d" % n):
                break
            time.sleep(0.1)
        return ":%d" % n

    def wait_pid(self, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            injected = [int(l[4:]) for l in self.lines if l.startswith("pid=")]
            if injected and IS_WINDOWS:
                self.pid = injected[0]
                return self.pid
            if injected:
                pids = memory.linux_pids(marker="ACHL_RUN_ID=" + self.run_id)
                if pids:
                    self.pid = pids[0]
                    return self.pid
            if self.proc.poll() is not None:
                said = " ".join(self.lines) or "exit code %s" % self.proc.returncode
                raise LaunchError("launcher exited early (%s), see launcher.log" % said)
            time.sleep(0.2)
        raise LaunchError("acs.exe did not start within %ds" % timeout)

    def alive(self):
        if self.pid is None:
            return self.proc is not None and self.proc.poll() is None
        if IS_WINDOWS:
            return self.proc.poll() is None
        return os.path.exists("/proc/%d" % self.pid)

    def stop(self):
        if self.pid and not IS_WINDOWS:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except OSError:
                pass
        if self.pid and IS_WINDOWS:
            subprocess.call(["taskkill", "/F", "/PID", str(self.pid)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.xvfb:
            self.xvfb.terminate()
            try:
                self.xvfb.wait(5)
            except subprocess.TimeoutExpired:
                self.xvfb.kill()
