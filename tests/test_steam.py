import os
import struct
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest import mock

from achl import cli, steam

USER_REG = """WINE REGISTRY Version 2

[Software\\\\Valve\\\\Steam] 1793964000
"Language"="english"

[Software\\\\Valve\\\\Steam\\\\ActiveProcess] 1793964646
#time=1dd6de2446c4292
"ActiveUser"=dword:%s
"pid"=dword:00000020

[Software\\\\Wine] 1793964000
"""


class SteamTest(unittest.TestCase):
    def test_user_reg(self):
        self.assertEqual(steam.parse_user_reg(USER_REG % "0000abcd"), 0xABCD)
        self.assertEqual(steam.parse_user_reg(USER_REG % "00000000"), 0)
        self.assertIsNone(steam.parse_user_reg("[Software\\\\Wine] 1\n"))

    def test_reg_query(self):
        out = ("\r\nHKEY_CURRENT_USER\\Software\\Valve\\Steam\\ActiveProcess\r\n"
               "    ActiveUser    REG_DWORD    0x1f2e3d\r\n\r\n")
        self.assertEqual(steam.parse_reg_query(out), 0x1F2E3D)
        self.assertIsNone(steam.parse_reg_query("reg: Unable to find the specified registry key"))

    def test_remembered(self):
        vdf = '"users"\n{\n\t"7656"\n\t{\n\t\t"AccountName"\t\t"x"\n\t\t"RememberPassword"\t\t"%s"\n\t}\n}\n'
        self.assertTrue(steam.remembered_text(vdf % "1"))
        self.assertFalse(steam.remembered_text(vdf % "0"))

    def test_process_matching(self):
        self.assertTrue(steam.is_main(["steam.exe", "-no-cef-sandbox"]))
        self.assertTrue(steam.is_main(["C:\\Program Files (x86)\\Steam\\steam.exe"]))
        self.assertFalse(steam.is_main(["sh", "-c", steam.SUPERVISOR, "achl-steam", "wine",
                                        "steam.exe"]))
        self.assertFalse(steam.is_steam(["sh", "-c", steam.SUPERVISOR, "achl-steam", "wine",
                                         "steam.exe"]))
        self.assertTrue(steam.is_steam(
            ["C:\\Program Files (x86)\\Steam\\bin\\cef\\cef.win64\\steamwebhelper.exe"]))
        self.assertTrue(steam.is_steam(
            ["C:\\Program Files (x86)\\Common Files\\Steam\\steamservice.exe"]))
        self.assertFalse(steam.is_steam(["Z:\\games\\assettocorsa\\acs.exe"]))

    def test_xauth_entry(self):
        e = steam.xauth_entry(b"k" * 16)
        family, alen = struct.unpack(">HH", e[:4])
        self.assertEqual((family, alen), (0xFFFF, 0))
        self.assertIn(b"MIT-MAGIC-COOKIE-1", e)
        self.assertTrue(e.endswith(struct.pack(">H", 16) + b"k" * 16))

    @unittest.skipIf(os.name == "nt", "POSIX paths")
    def test_prefix_default(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/d"}, clear=False):
            os.environ.pop("WINEPREFIX", None)
            self.assertEqual(steam.prefix_from(), "/d/ac-headless/prefix")
            self.assertEqual(steam.prefix_from("/p"), "/p")
            os.environ["WINEPREFIX"] = "/w"
            self.assertEqual(steam.prefix_from(), "/w")
            del os.environ["WINEPREFIX"]

    def test_ensure_ready_needs_steam(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(steam.SteamError) as e:
                steam.ensure_ready(t)
            self.assertIn("install.sh", str(e.exception))
            sd = steam.steam_dir(t)
            os.makedirs(sd)
            open(os.path.join(sd, "Steam.exe"), "wb").close()
            self.assertTrue(steam.installed(t))
            with mock.patch.object(steam, "main_pids", return_value=[]):
                with self.assertRaises(steam.SteamError) as e:
                    steam.ensure_ready(t)
            self.assertIn("steam login", str(e.exception))
            with mock.patch.object(steam, "main_pids", return_value=[123]), \
                    mock.patch.object(steam, "active_user", return_value=0), \
                    mock.patch.object(steam, "remembered", return_value=True), \
                    mock.patch.object(steam, "wait_logged_in", return_value=False):
                with self.assertRaises(steam.SteamError) as e:
                    steam.ensure_ready(t, log=lambda m: None)
            self.assertIn("not logged in", str(e.exception))
            with mock.patch.object(steam, "main_pids", return_value=[123]), \
                    mock.patch.object(steam, "active_user", return_value=42):
                steam.ensure_ready(t)

    def test_parser(self):
        a = cli.parser().parse_args(["steam", "login", "--type", "--prefix", "/p"])
        self.assertEqual((a.action, a.mode, a.prefix), ("login", "type", "/p"))
        a = cli.parser().parse_args(["steam", "status"])
        self.assertIsNone(a.mode)
        with self.assertRaises(SystemExit), redirect_stderr(StringIO()):
            cli.parser().parse_args(["steam", "login", "--type", "--vnc"])


if __name__ == "__main__":
    unittest.main()
