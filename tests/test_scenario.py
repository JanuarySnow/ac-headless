import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from achl import scenario, telemetry


def car(i, laps=3, best=95000, speed=150.0, stuck=0.0, off=0.0, fell=0.5, dist=7000.0):
    return {"car": i, "ai": i != 0, "laps_completed": laps,
            "laps": [{"lap": n + 1, "ms": best, "valid": True, "cuts": 0, "t": 0} for n in range(laps)],
            "best_lap_ms": best, "mean_lap_ms": best, "max_speed_kmh": speed, "distance_m": dist,
            "max_stuck_s": stuck, "offtrack_s": off, "start_y": 10.0, "min_y": 10.0 - fell,
            "fell_m": fell}


def results(cars, outcome="ok"):
    return {"outcome": outcome, "reason": "finished", "cars_loaded": len(cars), "cars": cars}


def sc(run, checks, d="."):
    return {"name": "t", "run": run, "assert": checks, "_dir": d}


RUN = {"mode": "hotlap", "track": "magione", "car": "bmw_m3_e30", "laps": 3}


class ScenarioTest(unittest.TestCase):
    def by(self, out):
        return {c["check"]: c["ok"] for c in out}

    def test_all_pass(self):
        out = scenario.evaluate(sc(RUN, [
            {"check": "laps_completed", "car": 0},
            {"check": "best_lap", "car": 0, "min_ms": 80000, "max_ms": 100000},
            {"check": "max_speed", "car": 0, "min_kmh": 100},
            {"check": "no_stuck"}, {"check": "offtrack"}, {"check": "no_fall"},
            {"check": "moved", "min_m": 1000}]), results([car(0)]))
        self.assertTrue(all(c["ok"] for c in out), out)
        self.assertEqual(out[0]["check"], "outcome")

    def test_failures(self):
        out = scenario.evaluate(sc(RUN, [
            {"check": "laps_completed", "car": 0, "min": 5},
            {"check": "best_lap", "car": 0, "max_ms": 90000},
            {"check": "no_stuck", "max_seconds": 5},
            {"check": "no_fall", "max_drop_m": 1}]),
            results([car(0, stuck=30, fell=50)], outcome="timeout"))
        self.assertEqual(self.by(out), {"outcome": False, "laps_completed": False,
                                        "best_lap": False, "no_stuck": False, "no_fall": False})

    def test_car_selection(self):
        r = results([car(0), car(1, laps=1), car(2)])
        run = dict(RUN, mode="race", ai=2)
        self.assertFalse(self.by(scenario.evaluate(sc(run, [
            {"check": "laps_completed", "car": "all", "min": 2}]), r))["laps_completed"])
        self.assertTrue(self.by(scenario.evaluate(sc(run, [
            {"check": "laps_completed", "car": 2, "min": 2}]), r))["laps_completed"])
        self.assertTrue(self.by(scenario.evaluate(sc(run, [{"check": "cars_loaded"}]), r))
                        ["cars_loaded"])
        self.assertFalse(self.by(scenario.evaluate(sc(run, [
            {"check": "laps_completed", "car": 7}]), r))["laps_completed"])

    def test_regression_baseline(self):
        with tempfile.TemporaryDirectory() as t:
            a = [{"check": "lap_time_regression", "car": 0, "baseline": "b.json",
                  "tolerance_pct": 1.0}]
            first = scenario.evaluate(sc(RUN, a, t), results([car(0, best=95000)]))
            self.assertTrue(first[1]["ok"])
            self.assertTrue(os.path.isfile(os.path.join(t, "b.json")))
            same = scenario.evaluate(sc(RUN, a, t), results([car(0, best=95500)]))
            self.assertTrue(same[1]["ok"], same)
            slow = scenario.evaluate(sc(RUN, a, t), results([car(0, best=97000)]))
            self.assertFalse(slow[1]["ok"])
            self.assertIn("+2.11%", slow[1]["message"])

    def test_load_validates(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "x.json")
            with open(p, "w") as fh:
                json.dump({"run": RUN, "assert": [{"check": "nope"}]}, fh)
            with self.assertRaises(scenario.ScenarioError):
                scenario.load(p)
            with open(p, "w") as fh:
                json.dump({"run": RUN, "assert": [{"check": "no_stuck"}]}, fh)
            self.assertEqual(scenario.load(p)["name"], "x")

    def test_examples_load(self):
        ex = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
        names = sorted(f for f in os.listdir(ex) if f.endswith(".json") and "baseline" not in f)
        self.assertGreaterEqual(len(names), 4)
        for f in names:
            scenario.load(os.path.join(ex, f))

    def test_junit(self):
        reports = [{"name": "a", "seconds": 1.0, "checks": [
            {"check": "outcome", "ok": True, "message": "ok"},
            {"check": "best_lap", "ok": False, "message": "car 0 best <slow> & late"}]}]
        root = ET.fromstring(scenario.junit(reports))
        self.assertEqual(root.get("tests"), "2")
        self.assertEqual(root.get("failures"), "1")
        self.assertEqual(len(root.findall(".//failure")), 1)


class TelemetryTest(unittest.TestCase):
    def snap(self, laps, speed, x, last=None, y=1.0, off=False, pit=False):
        return {"session": {"type": "practice", "order": [0]}, "cars": [{
            "car": 0, "pos": [x, y, 0.0], "speed_kmh": speed, "rpm": 5000.0, "gear": 3,
            "gas": 1.0, "brake": 0.0, "steer": 0.0, "fuel": 30.0, "npos": 0.5, "lateral": 0.0,
            "off_track": off, "in_pit": pit, "laps": laps, "last_lap_ms": last,
            "best_lap_ms": last, "last_lap_valid": True, "cuts": 0, "tyre_compound": 0,
            "ai": True}]}

    def test_pit_lane_is_not_off_track(self):
        rec = telemetry.Recorder(None, "csv")
        rec.sample(0.0, self.snap(0, 40, 0, off=True, pit=True))
        rec.sample(5.0, self.snap(0, 40, 0, off=True, pit=True))
        rec.sample(6.0, self.snap(0, 40, 0, off=True))
        rec.sample(7.0, self.snap(0, 40, 0))
        rec.close()
        self.assertEqual(rec.results()["cars"][0]["offtrack_s"], 1.0)

    def test_laps_stuck_and_files(self):
        with tempfile.TemporaryDirectory() as t:
            rec = telemetry.Recorder(t, "jsonl")
            rec.sample(0.0, self.snap(0, 100, 0))
            rec.sample(1.0, self.snap(0, 100, 30))
            rec.sample(2.0, self.snap(1, 100, 60, last=95000, off=True))
            for k in range(3, 10):
                rec.sample(float(k), self.snap(1, 0.5, 60, last=95000, y=-5.0))
            rec.close()
            r = rec.results()
            c = r["cars"][0]
            self.assertEqual(c["laps_completed"], 1)
            self.assertEqual(c["best_lap_ms"], 95000)
            self.assertEqual(c["max_stuck_s"], 6.0)
            self.assertEqual(c["distance_m"], 66.0)
            self.assertEqual(c["fell_m"], 6.0)
            self.assertEqual(c["offtrack_s"], 1.0)
            with open(os.path.join(t, "telemetry.jsonl")) as fh:
                self.assertEqual(len(fh.readlines()), 10)
            telemetry.write_laps_csv(os.path.join(t, "laps.csv"), r)
            with open(os.path.join(t, "laps.csv")) as fh:
                self.assertEqual(len(fh.readlines()), 2)


if __name__ == "__main__":
    unittest.main()
