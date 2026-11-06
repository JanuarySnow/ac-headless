import json
import os
import shutil
import time

from . import launch, memory, offsets, profile, raceini, state, telemetry

MODES = ("hotlap", "race", "practice")

DEFAULTS = {
    "mode": "hotlap", "track": None, "layout": "", "car": None, "ai": 0, "ai_level": 100,
    "ai_aggression": 0, "ai_cars": [], "laps": 3, "minutes": 10, "timeout": 900,
    "render": "off", "hz": 10, "format": "csv", "drive": True, "start_delay_ms": 3000,
    "load_timeout": 300, "memory_max": None, "grip": 100, "ambient": 22, "road": 28,
    "weather": "3_clear", "fuel_rate": 1, "tyre_wear": 1, "damage": 0, "spawn": None,
    "starting_position": 1, "player_name": "achl",
}


class RunError(Exception):
    pass


def spec_from(d):
    spec = dict(DEFAULTS)
    unknown = set(d) - set(DEFAULTS)
    if unknown:
        raise RunError("unknown run settings: %s" % ", ".join(sorted(unknown)))
    spec.update({k: v for k, v in d.items() if v is not None})
    if spec["mode"] not in MODES:
        raise RunError("mode must be one of %s" % ", ".join(MODES))
    if not spec["track"] or not spec["car"]:
        raise RunError("track and car are required")
    if spec["mode"] == "hotlap" and spec["ai"]:
        raise RunError("hotlap has no opponents, use race or practice for AI cars")
    return spec


def race_ini_for(spec, ac_dir):
    session = {"hotlap": "practice", "practice": "practice", "race": "race"}[spec["mode"]]
    cars = [spec["car"]] + list(spec["ai_cars"])
    skins = {c: raceini.first_skin(ac_dir, c) for c in cars}
    return raceini.build(
        track=spec["track"], layout=spec["layout"], car=spec["car"], session=session,
        laps=spec["laps"], minutes=max(spec["minutes"], 1) if spec["mode"] == "practice"
        else max(60, spec["minutes"]), ai=spec["ai"], ai_level=spec["ai_level"],
        ai_aggression=spec["ai_aggression"], ai_cars=spec["ai_cars"], skins=skins,
        player_name=spec["player_name"], starting_position=spec["starting_position"],
        ambient=spec["ambient"], road=spec["road"], weather=spec["weather"], grip=spec["grip"],
        fuel_rate=spec["fuel_rate"], tyre_wear=spec["tyre_wear"], damage=spec["damage"],
        spawn=spec["spawn"])


def read_states(log_path):
    found = []
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("state="):
                    found.append(line.split()[0][6:])
    except OSError:
        pass
    return found


def explain(reason, game_log):
    errors = []
    try:
        with open(game_log, encoding="utf-8", errors="replace") as fh:
            errors = [l.strip() for l in fh if l.startswith("ERROR:")]
    except OSError:
        pass
    if any("Steam init failed" in e for e in errors):
        return "AC could not reach Steam (its log says: ERROR: Steam init failed). Start Steam and log in first. On Linux check with: run.sh steam status"
    if errors:
        return "%s; last error in the AC log: %s" % (reason, errors[-1])
    return reason


def finished(spec, snap, t_drive):
    cars = [c for c in snap["cars"] if c]
    if not cars:
        return False
    player = cars[0]
    if spec["mode"] == "hotlap":
        return player["laps"] >= spec["laps"]
    if spec["mode"] == "race":
        s = snap.get("session") or {}
        return bool(s.get("over")) or player["laps"] >= spec["laps"]
    return t_drive >= spec["minutes"] * 60


def run(spec, ac_dir, out_dir, log=print):
    spec = spec_from(spec)
    ac_dir = os.path.abspath(ac_dir)
    exe = os.path.join(ac_dir, "acs.exe")
    if not os.path.isfile(exe):
        raise RunError("no acs.exe in %s" % ac_dir)
    version, kind = offsets.identify(exe)
    offs = offsets.Offsets(version)
    problems = raceini.check_content(ac_dir, spec["track"], spec["layout"],
                                     [spec["car"]] + list(spec["ai_cars"]))
    if problems:
        raise RunError("; ".join(problems))
    if os.path.isfile(os.path.join(ac_dir, "dwrite.dll")):
        log("warning: Custom Shaders Patch (dwrite.dll) is installed in this AC folder; "
            "headless runs are only tested without it")
    os.makedirs(out_dir, exist_ok=True)
    docs = os.path.join(out_dir, "profile")
    profile.build(docs, race_ini_for(spec, ac_dir))
    dll_log = os.path.join(out_dir, "achl.log")
    env = launch.dll_env(spec["render"], offs, docs, dll_log, drive=spec["drive"],
                         start_race=spec["mode"] == "race", start_delay_ms=spec["start_delay_ms"],
                         wait_s=spec["load_timeout"])
    log("AC %s (%s), %s at %s%s with %s" % (version, kind, spec["mode"], spec["track"],
                                           "/" + spec["layout"] if spec["layout"] else "",
                                           spec["car"]))
    game = launch.Game(ac_dir, env, out_dir, memory_max=spec["memory_max"])
    rec = telemetry.Recorder(out_dir if spec["format"] != "none" else None,
                             spec["format"] if spec["format"] != "none" else "csv")
    t0 = time.time()
    outcome, reason = "error", ""
    reader = None
    try:
        game.start()
        pid = game.wait_pid()
        log("acs.exe pid %d" % pid)
        time.sleep(1.0)
        reader = memory.open_process(pid)
        g = state.Game(reader, offs)
        t_drive = None
        period = 1.0 / max(1, spec["hz"])
        reported = set()
        while True:
            now = time.time() - t0
            if now > spec["timeout"]:
                outcome, reason = "timeout", "timeout after %ds" % spec["timeout"]
                break
            if not game.alive():
                outcome, reason = "crashed", explain("acs.exe exited", profile.game_log(docs))
                break
            states = read_states(dll_log)
            for s in states:
                if s not in reported:
                    reported.add(s)
                    log("  %s (%.0fs)" % (s.replace("_", " "), now))
            if "no_session" in states or "ai_failed" in states:
                outcome, reason = "error", "game reported %s" % states[-1]
                break
            if not spec["drive"] and t_drive is None and ("loaded" in states or g.loaded()):
                t_drive = now
            if spec["drive"] and "ai_driving" in states and t_drive is None:
                t_drive = now
            if now > spec["load_timeout"] and t_drive is None:
                outcome, reason = "error", "session did not load in %ds" % spec["load_timeout"]
                break
            if t_drive is not None:
                try:
                    snap = g.snapshot()
                except memory.ReadError:
                    snap = None
                if snap:
                    rec.sample(now - t_drive, snap)
                    if finished(spec, snap, now - t_drive):
                        outcome, reason = "ok", "finished"
                        break
            time.sleep(period)
    except (launch.LaunchError, memory.ReadError) as e:
        outcome, reason = "error", explain(str(e), profile.game_log(docs))
    finally:
        rec.close()
        if reader:
            reader.close()
        game.stop()
        game_log = profile.game_log(docs)
        if os.path.isfile(game_log):
            shutil.copyfile(game_log, os.path.join(out_dir, "ac_log.txt"))
    results = rec.results({"outcome": outcome, "reason": reason, "ac_version": version,
                           "exe": kind, "spec": spec, "wall_s": round(time.time() - t0, 1)})
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    telemetry.write_laps_csv(os.path.join(out_dir, "laps.csv"), results)
    return results


def print_summary(results, log=print):
    log("outcome: %s (%s)" % (results["outcome"], results["reason"]))
    for car in results["cars"]:
        log("  car %d%s: %d laps, best %s, max %.0f km/h" % (
            car["car"], " (AI)" if car["ai"] else "", car["laps_completed"],
            state.fmt_ms(car["best_lap_ms"]), car["max_speed_kmh"]))
