import os
import tempfile
import unittest

from achl import drive, raceini


class RaceIniTest(unittest.TestCase):
    def test_practice_single_car(self):
        d = raceini.parse(raceini.build("magione", "bmw_m3_e30"))
        self.assertEqual(d["RACE"]["TRACK"], "magione")
        self.assertEqual(d["RACE"]["CARS"], "1")
        self.assertEqual(d["CAR_0"]["MODEL"], "-")
        self.assertEqual(d["SESSION_0"]["TYPE"], "1")
        self.assertEqual(d["SESSION_0"]["SPAWN_SET"], "PIT")
        self.assertNotIn("CAR_1", d)
        self.assertEqual(d["REPLAY"]["ACTIVE"], "0")

    def test_race_with_mixed_grid(self):
        text = raceini.build("ks_brands_hatch", "ks_mazda_mx5_cup", layout="indy",
                             session="race", laps=7, ai=3, ai_level=90,
                             ai_cars=["bmw_m3_e30", "abarth500"], starting_position=4)
        d = raceini.parse(text)
        self.assertEqual(d["RACE"]["CONFIG_TRACK"], "indy")
        self.assertEqual(d["RACE"]["CARS"], "4")
        self.assertEqual(d["RACE"]["RACE_LAPS"], "7")
        self.assertEqual(d["SESSION_0"]["TYPE"], "3")
        self.assertEqual(d["SESSION_0"]["LAPS"], "7")
        self.assertEqual(d["SESSION_0"]["SPAWN_SET"], "START")
        self.assertEqual(d["SESSION_0"]["STARTING_POSITION"], "4")
        self.assertEqual([d["CAR_%d" % i]["MODEL"] for i in (1, 2, 3)],
                         ["bmw_m3_e30", "abarth500", "bmw_m3_e30"])
        self.assertEqual(d["CAR_2"]["AI_LEVEL"], "90")

    def test_bad_session(self):
        with self.assertRaises(ValueError):
            raceini.build("magione", "bmw_m3_e30", session="drift")

    def test_write_uses_crlf(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "cfg", "race.ini")
            raceini.write(p, raceini.build("magione", "bmw_m3_e30"))
            with open(p, "rb") as fh:
                self.assertIn(b"[RACE]\r\n", fh.read())

    def test_content_check_and_skin(self):
        with tempfile.TemporaryDirectory() as ac:
            os.makedirs(os.path.join(ac, "content", "tracks", "magione"))
            os.makedirs(os.path.join(ac, "content", "cars", "bmw_m3_e30", "skins", "b_blue"))
            os.makedirs(os.path.join(ac, "content", "cars", "bmw_m3_e30", "skins", "a_red"))
            self.assertEqual(raceini.first_skin(ac, "bmw_m3_e30"), "a_red")
            self.assertEqual(raceini.check_content(ac, "magione", "", ["bmw_m3_e30"]), [])
            probs = raceini.check_content(ac, "magione", "gp", ["nope"])
            self.assertEqual(len(probs), 2)

    def test_hotlap_spec_is_long_practice(self):
        spec = drive.spec_from({"mode": "hotlap", "track": "magione", "car": "bmw_m3_e30"})
        d = raceini.parse(drive.race_ini_for(spec, "/nonexistent"))
        self.assertEqual(d["SESSION_0"]["TYPE"], "1")
        self.assertGreaterEqual(int(d["SESSION_0"]["DURATION_MINUTES"]), 60)

    def test_spec_rejects_bad_input(self):
        with self.assertRaises(drive.RunError):
            drive.spec_from({"mode": "hotlap", "track": "magione"})
        with self.assertRaises(drive.RunError):
            drive.spec_from({"mode": "hotlap", "track": "a", "car": "b", "ai": 3})
        with self.assertRaises(drive.RunError):
            drive.spec_from({"mode": "race", "track": "a", "car": "b", "lapz": 3})

    def test_explain_reads_ac_log(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "log.txt")
            self.assertEqual(drive.explain("boom", p), "boom")
            with open(p, "w") as fh:
                fh.write("Installing CrashGuard Fault Handler\nERROR: Steam init failed\n")
            self.assertIn("Start Steam", drive.explain("boom", p))
            with open(p, "w") as fh:
                fh.write("ERROR: something else\n")
            self.assertIn("something else", drive.explain("boom", p))


if __name__ == "__main__":
    unittest.main()
