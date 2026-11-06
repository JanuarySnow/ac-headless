import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout
from io import StringIO

from achl import cli, launch, offsets
from tests.test_offsets import fake_pe


class CliTest(unittest.TestCase):
    def make_ac(self, root):
        b = offsets.BUILDS["1.16.4"]["pe"]
        os.makedirs(root)
        with open(os.path.join(root, "acs.exe"), "wb") as fh:
            fh.write(fake_pe(b["timestamp"], b["size_of_image"][0]))

    def test_install_and_uninstall(self):
        with tempfile.TemporaryDirectory() as t:
            ac, binp = os.path.join(t, "ac"), os.path.join(t, "bin")
            self.make_ac(ac)
            os.makedirs(binp)
            for f in (launch.DLL, launch.LAUNCHER):
                with open(os.path.join(binp, f), "wb") as fh:
                    fh.write(b"x")
            with redirect_stdout(StringIO()):
                self.assertEqual(cli.main(["install", "--ac", ac, "--from", binp]), 0)
            dest = os.path.join(ac, "achl")
            with open(os.path.join(dest, "installed.json")) as fh:
                self.assertEqual(len(json.load(fh)["files"]), 3)
            with open(os.path.join(ac, "steam_appid.txt")) as fh:
                self.assertEqual(fh.read(), "244210")
            with redirect_stdout(StringIO()):
                self.assertEqual(cli.main(["uninstall", "--ac", ac]), 0)
            self.assertFalse(os.path.exists(dest))
            self.assertEqual(sorted(os.listdir(ac)), ["acs.exe"])

    def test_install_keeps_existing_steam_appid(self):
        with tempfile.TemporaryDirectory() as t:
            ac, binp = os.path.join(t, "ac"), os.path.join(t, "bin")
            self.make_ac(ac)
            with open(os.path.join(ac, "steam_appid.txt"), "w") as fh:
                fh.write("244210")
            os.makedirs(binp)
            for f in (launch.DLL, launch.LAUNCHER):
                with open(os.path.join(binp, f), "wb") as fh:
                    fh.write(b"x")
            with redirect_stdout(StringIO()):
                cli.main(["install", "--ac", ac, "--from", binp])
                cli.main(["uninstall", "--ac", ac])
            self.assertEqual(sorted(os.listdir(ac)), ["acs.exe", "steam_appid.txt"])

    def test_install_refuses_unknown_build(self):
        with tempfile.TemporaryDirectory() as t:
            ac = os.path.join(t, "ac")
            os.makedirs(ac)
            with open(os.path.join(ac, "acs.exe"), "wb") as fh:
                fh.write(fake_pe(1, 2))
            with self.assertRaises(SystemExit) as e:
                cli.main(["install", "--ac", ac, "--from", t])
            self.assertIn("not a build", str(e.exception))

    def test_dll_env(self):
        env = launch.dll_env("off", offsets.Offsets("1.16.4"), "/x/profile", "/x/achl.log",
                             drive=True, start_race=True)
        self.assertEqual(env["ACHL_AUTODRIVE"], "1")
        self.assertEqual(env["ACHL_AUTOSTART"], "1")
        self.assertEqual(env["ACHL_RENDER_OFF"], "1")
        self.assertIn("pyi=1559af0", env["ACHL_OFFSETS"])
        on = launch.dll_env("on", offsets.Offsets("1.16.4"), "/x", "/x/l")
        self.assertNotIn("ACHL_RENDER_OFF", on)
        self.assertNotIn("ACHL_AUTODRIVE", on)

    def test_parser(self):
        a = cli.parser().parse_args(["run", "race", "--track", "magione", "--car", "c",
                                     "--ai", "5", "--ai-car", "x", "--ai-car", "y"])
        spec = cli.spec_from_args(a, a.mode)
        self.assertEqual(spec["ai_cars"], ["x", "y"])
        self.assertEqual(spec["ai"], 5)
        self.assertTrue(spec["drive"])

    def test_memory_cap_falls_back_without_user_bus(self):
        said = []
        fail = subprocess.CompletedProcess([], 1)
        with mock.patch("shutil.which", return_value="/usr/bin/systemd-run"), \
                mock.patch("subprocess.run", return_value=fail):
            self.assertEqual(launch.memory_cap("3G", said.append), [])
        self.assertIn("without a memory cap", said[0])

    def test_memory_cap_used_when_bus_works(self):
        ok = subprocess.CompletedProcess([], 0)
        with mock.patch("shutil.which", return_value="/usr/bin/systemd-run"), \
                mock.patch("subprocess.run", return_value=ok):
            cap = launch.memory_cap("3G", print)
        self.assertEqual(cap[:3], ["systemd-run", "--user", "--scope"])
        self.assertIn("MemoryMax=3G", cap)
        self.assertEqual(launch.memory_cap(None), [])


if __name__ == "__main__":
    unittest.main()
