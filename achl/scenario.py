import json
import os
import time
from xml.sax.saxutils import escape, quoteattr

from . import drive


class ScenarioError(Exception):
    pass


def load(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "run" not in data:
        raise ScenarioError("%s: a scenario needs a \"run\" object" % path)
    data.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    data.setdefault("assert", [])
    data["_dir"] = os.path.dirname(os.path.abspath(path))
    for a in data["assert"]:
        if a.get("check") not in CHECKS:
            raise ScenarioError("%s: unknown check %r" % (path, a.get("check")))
    drive.spec_from(data["run"])
    return data


def _cars(results, which):
    cars = results.get("cars", [])
    if which in (None, "all"):
        return cars
    if which == "ai":
        return [c for c in cars if c["car"] != 0]
    if isinstance(which, int):
        return [c for c in cars if c["car"] == which]
    raise ScenarioError("car must be a number, \"all\" or \"ai\"")


def _each(results, a, test):
    cars = _cars(results, a.get("car", 0))
    if not cars:
        return False, "no data for car %s" % a.get("car", 0)
    bad = [m for m in (test(c) for c in cars) if m]
    return (not bad), "; ".join(bad) if bad else "%d car(s) ok" % len(cars)


def c_outcome(results, a, ctx):
    want = a.get("is", "ok")
    got = results.get("outcome")
    return got == want, "outcome %s (%s)" % (got, results.get("reason", ""))


def c_cars_loaded(results, a, ctx):
    n = results.get("cars_loaded", 0)
    want = a.get("min", 1 + ctx["run"].get("ai", 0))
    return n >= want, "%d cars loaded, wanted %d" % (n, want)


def c_laps_completed(results, a, ctx):
    want = a.get("min", ctx["run"].get("laps", 1))

    def t(c):
        if c["laps_completed"] < want:
            return "car %d did %d laps, wanted %d" % (c["car"], c["laps_completed"], want)
    return _each(results, a, t)


def c_best_lap(results, a, ctx):
    lo, hi = a.get("min_ms"), a.get("max_ms")

    def t(c):
        b = c["best_lap_ms"]
        if b is None:
            return "car %d has no timed lap" % c["car"]
        if lo is not None and b < lo:
            return "car %d best %d ms is under %d" % (c["car"], b, lo)
        if hi is not None and b > hi:
            return "car %d best %d ms is over %d" % (c["car"], b, hi)
    return _each(results, a, t)


def c_max_speed(results, a, ctx):
    lo, hi = a.get("min_kmh"), a.get("max_kmh")

    def t(c):
        v = c["max_speed_kmh"]
        if lo is not None and v < lo:
            return "car %d top speed %.1f under %s" % (c["car"], v, lo)
        if hi is not None and v > hi:
            return "car %d top speed %.1f over %s" % (c["car"], v, hi)
    return _each(results, a, t)


def c_no_stuck(results, a, ctx):
    limit = a.get("max_seconds", 15)

    def t(c):
        if c["max_stuck_s"] > limit:
            return "car %d stood still for %.0f s" % (c["car"], c["max_stuck_s"])
    return _each(results, a, t)


def c_offtrack(results, a, ctx):
    limit = a.get("max_seconds", 5)

    def t(c):
        if c["offtrack_s"] > limit:
            return "car %d was off track for %.1f s" % (c["car"], c["offtrack_s"])
    return _each(results, a, t)


def c_no_fall(results, a, ctx):
    limit = a.get("max_drop_m", 20)

    def t(c):
        if c["fell_m"] is None:
            return "car %d has no position data" % c["car"]
        if c["fell_m"] > limit:
            return "car %d dropped %.1f m below its spawn" % (c["car"], c["fell_m"])
    return _each(results, a, t)


def c_moved(results, a, ctx):
    want = a.get("min_m", 50)

    def t(c):
        if c["distance_m"] < want:
            return "car %d moved %.0f m, wanted %d" % (c["car"], c["distance_m"], want)
    return _each(results, a, t)


def c_lap_regression(results, a, ctx):
    path = a.get("baseline")
    if not path:
        raise ScenarioError("lap_time_regression needs a baseline file")
    if not os.path.isabs(path):
        path = os.path.join(ctx["dir"], path)
    tol = float(a.get("tolerance_pct", 1.0))
    if not os.path.isfile(path):
        if a.get("write_missing", True):
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"cars": [{"car": c["car"], "best_lap_ms": c["best_lap_ms"]}
                                    for c in results.get("cars", [])]}, fh, indent=2)
            return True, "baseline written to %s" % path
        return False, "baseline %s missing" % path
    with open(path, encoding="utf-8") as fh:
        base = {c["car"]: c["best_lap_ms"] for c in json.load(fh).get("cars", [])}

    def t(c):
        ref = base.get(c["car"])
        if not ref:
            return "car %d not in baseline" % c["car"]
        if c["best_lap_ms"] is None:
            return "car %d has no timed lap" % c["car"]
        diff = 100.0 * (c["best_lap_ms"] - ref) / ref
        if abs(diff) > tol:
            return "car %d best %d ms is %+.2f%% off baseline %d" % (c["car"], c["best_lap_ms"],
                                                                    diff, ref)
    return _each(results, a, t)


CHECKS = {
    "outcome": c_outcome,
    "cars_loaded": c_cars_loaded,
    "laps_completed": c_laps_completed,
    "best_lap": c_best_lap,
    "max_speed": c_max_speed,
    "no_stuck": c_no_stuck,
    "offtrack": c_offtrack,
    "no_fall": c_no_fall,
    "moved": c_moved,
    "lap_time_regression": c_lap_regression,
}


def evaluate(scenario, results):
    ctx = {"run": scenario["run"], "dir": scenario.get("_dir", ".")}
    checks = list(scenario["assert"])
    if not any(a.get("check") == "outcome" for a in checks):
        checks.insert(0, {"check": "outcome", "is": "ok"})
    out = []
    for a in checks:
        try:
            ok, msg = CHECKS[a["check"]](results, a, ctx)
        except ScenarioError as e:
            ok, msg = False, str(e)
        out.append({"check": a["check"], "ok": bool(ok), "message": msg})
    return out


def run_file(path, ac_dir, out_root, log=print, overrides=None):
    sc = load(path)
    if overrides:
        sc["run"].update(overrides)
    out_dir = os.path.join(out_root, sc["name"])
    t0 = time.time()
    try:
        results = drive.run(sc["run"], ac_dir, out_dir, log=log)
    except Exception as e:
        results = {"outcome": "error", "reason": "%s: %s" % (type(e).__name__, e), "cars": []}
    checks = evaluate(sc, results)
    return {"name": sc["name"], "file": path, "seconds": round(time.time() - t0, 1),
            "passed": all(c["ok"] for c in checks), "checks": checks, "out": out_dir}


def junit(reports):
    tests = sum(len(r["checks"]) for r in reports)
    failures = sum(1 for r in reports for c in r["checks"] if not c["ok"])
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<testsuites tests="%d" failures="%d">' % (tests, failures)]
    for r in reports:
        fails = sum(1 for c in r["checks"] if not c["ok"])
        lines.append('  <testsuite name=%s tests="%d" failures="%d" time="%.1f">' % (
            quoteattr(r["name"]), len(r["checks"]), fails, r["seconds"]))
        for i, c in enumerate(r["checks"]):
            lines.append('    <testcase classname=%s name=%s>' % (
                quoteattr(r["name"]), quoteattr("%d %s" % (i + 1, c["check"]))))
            if not c["ok"]:
                lines.append('      <failure message=%s>%s</failure>' % (
                    quoteattr(c["message"]), escape(c["message"])))
            lines.append('    </testcase>')
        lines.append('  </testsuite>')
    lines.append('</testsuites>')
    return "\n".join(lines) + "\n"
