import io
import os
import struct
import tarfile
import tempfile
import time
import unittest
from unittest import mock

try:
    import pty
    import termios
except ImportError:
    raise unittest.SkipTest("needs a POSIX terminal")

from achl import cli, linuxsetup, login, screen, steam

BG = (28, 29, 33)
RED = (193, 87, 87)
WHITE = (255, 255, 255)
DARK = (21, 23, 28)


def blank(w=400, h=300, color=BG):
    px = bytes((color[2], color[1], color[0], 0)) * (w * h)
    return screen.Image(w, h, bytearray(px))


def paint(img, x0, y0, x1, y1, color):
    for y in range(int(y0), int(y1)):
        for x in range(int(x0), int(x1)):
            i = (y * img.width + x) * 4
            img.data[i:i + 3] = bytes((color[2], color[1], color[0]))


def sample_matrix(n=25):
    m = [[(r * 7 + c * 3) % 5 == 0 for c in range(n)] for r in range(n)]
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        for r in range(-1, 8):
            for c in range(-1, 8):
                if 0 <= r0 + r < n and 0 <= c0 + c < n:
                    ring = max(abs(r - 3), abs(c - 3))
                    m[r0 + r][c0 + c] = ring != 2 and ring <= 3
    return m


def draw_qr(m, module=3.9, at=(220, 60)):
    img = blank()
    n = len(m)
    side = n * module
    paint(img, at[0] - 20, at[1] - 20, at[0] + side + 20, at[1] + side + 20, WHITE)
    for r in range(n):
        for c in range(n):
            if m[r][c]:
                paint(img, round(at[0] + c * module), round(at[1] + r * module),
                      round(at[0] + (c + 1) * module), round(at[1] + (r + 1) * module), DARK)
    return img


class ScreenTest(unittest.TestCase):
    def test_cookie_roundtrip(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "xa")
            with open(p, "wb") as fh:
                fh.write(steam.xauth_entry(b"c" * 16))
            self.assertEqual(screen.read_cookie(p), b"c" * 16)
            with open(p, "wb") as fh:
                fh.write(b"\x01")
            self.assertIsNone(screen.read_cookie(p))

    def test_parse_setup(self):
        vendor = b"Xvfb"
        fixed = struct.pack("<IIIIHHBBBBBBBB4x", 1, 0, 0, 0, len(vendor), 0xFFFF, 1, 2, 0, 0,
                            32, 32, 8, 255)
        fmts = struct.pack("<BBB5x", 1, 1, 32) + struct.pack("<BBB5x", 24, 32, 32)
        scr = struct.pack("<IIIIIHHHHHHIBBBB", 0x2A, 0, 0, 0, 0, 1280, 800, 0, 0, 1, 1, 0x21,
                          0, 0, 24, 1)
        extra = fixed + vendor + fmts + scr
        self.assertEqual(screen.parse_setup(extra), (0x2A, 1280, 800, 24, 32))

    def test_look_and_fields(self):
        img = blank()
        self.assertEqual(screen.look(img)["error"], False)
        for top in (40, 100):
            paint(img, 20, top, 260, top + 1, RED)
            paint(img, 20, top + 40, 260, top + 41, RED)
        self.assertTrue(screen.look(img)["error"])
        self.assertEqual(screen.red_fields(img), [(139, 60), (139, 120)])

    def test_qr_roundtrip(self):
        m = sample_matrix()
        self.assertTrue(screen.finder_ok(m))
        img = draw_qr(m)
        self.assertTrue(screen.look(img)["form"])
        self.assertEqual(screen.qr_matrix(img), m)
        text = screen.qr_text(m)
        self.assertEqual(len(text.splitlines()), (25 + 4 + 1) // 2)

    def test_no_qr_on_plain_screen(self):
        self.assertIsNone(screen.qr_matrix(blank()))
        self.assertFalse(screen.look(blank())["form"])


class TerminalTest(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = pty.openpty()
        self.out = io.StringIO()
        self.term = login.Terminal(self.slave, self.out)

    def tearDown(self):
        os.close(self.master)
        os.close(self.slave)

    def test_needs_tty(self):
        r, w = os.pipe()
        try:
            with self.assertRaises(steam.SteamError):
                login.Terminal(r)
        finally:
            os.close(r)
            os.close(w)

    def test_answer(self):
        os.write(self.master, b"someone\n")
        self.assertEqual(self.term.ask("name: ", timeout=5), "someone")
        self.assertEqual(self.out.getvalue(), "name: ")

    def test_secret_turns_echo_off_and_back(self):
        seen = []
        real = termios.tcsetattr

        def spy(fd, when, attrs):
            seen.append(bool(attrs[3] & termios.ECHO))
            return real(fd, when, attrs)

        os.write(self.master, b"pw\n")
        with mock.patch.object(termios, "tcsetattr", side_effect=spy):
            self.assertEqual(self.term.ask("pw: ", secret=True, timeout=5), "pw")
        self.assertEqual(seen, [False, True])

    def test_timeout(self):
        with self.assertRaises(login.PromptTimeout):
            self.term.ask("x: ", timeout=0.3)

    def test_done_while_waiting(self):
        t = time.time()
        self.assertIsNone(self.term.ask("code: ", timeout=30, done=lambda: True))
        self.assertLess(time.time() - t, 5)


class FakeWatch:
    def __init__(self, states):
        self.states = list(states)

    def logged_in(self):
        return self.states[0] == "ok"

    def look(self):
        s = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"error": s == "error", "form": s == "form"}, s


class OutcomeTest(unittest.TestCase):
    def run_outcome(self, states, **kw):
        clock = [0.0]
        with mock.patch.object(time, "time", side_effect=lambda: clock[0]):
            def sleep(s):
                clock[0] += s
            return login.outcome(FakeWatch(states), 60, sleep=sleep, **kw)[0]

    def test_ok(self):
        self.assertEqual(self.run_outcome(["ok"]), "ok")

    def test_wrong_password(self):
        self.assertEqual(self.run_outcome(["form", "error", "error"]), "error")
        self.assertEqual(self.run_outcome(["error", "error"]), "error")

    def test_old_error_is_not_new(self):
        self.assertEqual(self.run_outcome(["error", "error", "other", "error", "error"],
                                          stale=True), "error")
        self.assertEqual(self.run_outcome(["error"] * 3 + ["other"] * 20, stale=True), "guard")
        self.assertEqual(self.run_outcome(["error"] * 40, stale=True), "error")

    def test_guard(self):
        self.assertEqual(self.run_outcome(["form", "other", "other", "other", "other", "other",
                                           "other", "other"]), "guard")

    def test_timeout(self):
        self.assertEqual(self.run_outcome(["form"]), "timeout")
        self.assertEqual(self.run_outcome(["other"], guard_after=1e9), "timeout")


class RunCleanupTest(unittest.TestCase):
    def patches(self, running):
        state = {"pid": 7 if running else None}

        def start(prefix, show=False, log=print):
            state["pid"] = 9

        return [mock.patch.object(steam, "installed", return_value=True),
                mock.patch.object(steam, "active_user", return_value=0),
                mock.patch.object(steam, "remembered", return_value=False),
                mock.patch.object(steam, "running_display",
                                  side_effect=lambda p: (state["pid"], ":91", "/x")),
                mock.patch.object(steam, "start", side_effect=start),
                mock.patch.object(login, "type_login",
                                  side_effect=steam.SteamError("wrong password 3 times"))]

    def go(self, running):
        ps = self.patches(running)
        for p in ps:
            p.start()
        try:
            with mock.patch.object(steam, "stop") as stop:
                with self.assertRaises(steam.SteamError):
                    login.run("/p", "type", term=object(), log=lambda m: None)
            return stop.called
        finally:
            for p in ps:
                p.stop()

    def test_stops_steam_it_started(self):
        self.assertTrue(self.go(running=False))

    def test_leaves_running_steam(self):
        self.assertFalse(self.go(running=True))


class SteamcmdTest(unittest.TestCase):
    def test_args(self):
        a = linuxsetup.steamcmd_args("/games/ac", "someone")
        self.assertEqual(a[:2], ["+@sSteamCmdForcePlatformType", "windows"])
        self.assertLess(a.index("+force_install_dir"), a.index("+login"))
        self.assertEqual(a[a.index("+login") + 1], "someone")
        self.assertEqual(a[-4:], ["+app_update", "244210", "validate", "+quit"])
        self.assertEqual(len(a), 10)

    def test_skips_when_present(self):
        said = []
        with mock.patch.object(linuxsetup, "run_steamcmd") as run:
            linuxsetup.install_ac("/x", "u", log=said.append, check=lambda d: "1.16.4")
        run.assert_not_called()
        self.assertIn("already", said[0])

    def test_refuses_unknown_exe(self):
        with tempfile.TemporaryDirectory() as t:
            open(os.path.join(t, "acs.exe"), "wb").close()
            with self.assertRaises(linuxsetup.SetupError):
                linuxsetup.install_ac(t, "u", check=lambda d: None)

    def test_disk_check(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(linuxsetup.SetupError) as e:
                linuxsetup.install_ac(t, "u", need_gb=10 ** 9, check=lambda d: None)
            self.assertIn("GB free", str(e.exception))

    def test_needs_user_without_tty(self):
        with tempfile.TemporaryDirectory() as t, \
                mock.patch("sys.stdin", io.StringIO()):
            with self.assertRaises(linuxsetup.SetupError) as e:
                linuxsetup.install_ac(t, None, need_gb=0, check=lambda d: None)
            self.assertIn("--steam-user", str(e.exception))

    def test_failed_download(self):
        with tempfile.TemporaryDirectory() as t, \
                mock.patch.object(linuxsetup, "run_steamcmd", return_value=5):
            with self.assertRaises(linuxsetup.SetupError) as e:
                linuxsetup.install_ac(t, "u", need_gb=0, check=lambda d: None, log=lambda m: None)
            self.assertIn("code 5", str(e.exception))

    def test_steamcmd_gets_own_home(self):
        with tempfile.TemporaryDirectory() as t, \
                mock.patch.object(linuxsetup, "get_steamcmd", return_value=t), \
                mock.patch("subprocess.Popen") as popen:
            popen.return_value.wait.return_value = 0
            self.assertEqual(linuxsetup.run_steamcmd(["+quit"]), 0)
            args, kw = popen.call_args
            self.assertEqual(args[0], [os.path.join(t, "steamcmd.sh"), "+quit"])
            self.assertEqual(kw["env"]["HOME"], os.path.join(t, "home"))
            self.assertNotIn("stdin", kw)

    def test_tar_traversal_refused(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "bad.tar.gz")
            with tarfile.open(p, "w:gz") as tf:
                info = tarfile.TarInfo("../evil")
                info.size = 1
                tf.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(linuxsetup.SetupError):
                linuxsetup.extract_tar(p, os.path.join(t, "out"))
            self.assertFalse(os.path.exists(os.path.join(t, "evil")))


class ParserTest(unittest.TestCase):
    def test_login_modes(self):
        a = cli.parser().parse_args(["steam", "login", "--qr"])
        self.assertEqual(a.mode, "qr")
        a = cli.parser().parse_args(["steam", "login"])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPLAY", None)
            self.assertEqual(cli.login_mode(a), "type")
            os.environ["DISPLAY"] = ":5"
            self.assertEqual(cli.login_mode(a), "window")

    def test_setup_install_ac(self):
        a = cli.parser().parse_args(["setup", "--install-ac", "/g/ac", "--steam-user", "u",
                                     "--no-login"])
        self.assertEqual((a.install_ac, a.steam_user, a.no_login), ("/g/ac", "u", True))


if __name__ == "__main__":
    unittest.main()
