import csv
import json
import math
import os

COLUMNS = ["t", "car", "laps", "npos", "speed_kmh", "rpm", "gear", "gas", "brake", "steer",
           "fuel", "x", "y", "z", "in_pit", "off_track", "tyre_compound"]

STUCK_KMH = 2.0


class Writer:
    def __init__(self, path, fmt):
        self.fmt = fmt
        self.fh = open(path, "w", newline="", encoding="utf-8")
        if fmt == "csv":
            self.csv = csv.writer(self.fh)
            self.csv.writerow(COLUMNS)

    def row(self, t, c):
        rec = {"t": round(t, 3), "car": c["car"], "laps": c["laps"], "npos": round(c["npos"], 5),
               "speed_kmh": round(c["speed_kmh"], 2), "rpm": round(c["rpm"]), "gear": c["gear"],
               "gas": round(c["gas"], 3), "brake": round(c["brake"], 3),
               "steer": round(c["steer"], 3), "fuel": round(c["fuel"], 3),
               "x": round(c["pos"][0], 3), "y": round(c["pos"][1], 3), "z": round(c["pos"][2], 3),
               "in_pit": int(c["in_pit"]), "off_track": int(c["off_track"]),
               "tyre_compound": c["tyre_compound"]}
        if self.fmt == "csv":
            self.csv.writerow([rec[k] for k in COLUMNS])
        else:
            self.fh.write(json.dumps(rec) + "\n")

    def close(self):
        self.fh.close()


class CarStats:
    def __init__(self, index):
        self.index = index
        self.laps = []
        self.lap_count = None
        self.max_speed = 0.0
        self.start = None
        self.last = None
        self.distance = 0.0
        self.min_y = None
        self.start_y = None
        self.stuck_since = None
        self.max_stuck = 0.0
        self.offtrack = 0.0
        self.moving_seen = False
        self.ai = False
        self.prev_t = None

    def update(self, t, c):
        pos = c["pos"]
        if not all(math.isfinite(v) for v in pos):
            return
        if self.start is None:
            self.start = pos
            self.start_y = pos[1]
            self.min_y = pos[1]
            self.lap_count = c["laps"]
        if self.last is not None:
            self.distance += math.dist(self.last, pos)
        self.last = pos
        self.min_y = min(self.min_y, pos[1])
        self.max_speed = max(self.max_speed, c["speed_kmh"])
        self.ai = self.ai or c["ai"]
        dt = 0.0 if self.prev_t is None else t - self.prev_t
        self.prev_t = t
        if c["off_track"] and not c["in_pit"]:
            self.offtrack += dt
        if c["speed_kmh"] > 10:
            self.moving_seen = True
        if self.moving_seen and c["speed_kmh"] < STUCK_KMH and not c["in_pit"]:
            if self.stuck_since is None:
                self.stuck_since = t
            self.max_stuck = max(self.max_stuck, t - self.stuck_since)
        else:
            self.stuck_since = None
        if c["laps"] != self.lap_count:
            if c["laps"] > self.lap_count:
                self.laps.append({"lap": c["laps"], "ms": c["last_lap_ms"],
                                  "valid": c["last_lap_valid"], "cuts": c["cuts"], "t": round(t, 3)})
            self.lap_count = c["laps"]

    def summary(self):
        timed = [l["ms"] for l in self.laps if l["ms"]]
        valid = [l["ms"] for l in self.laps if l["ms"] and l["valid"]]
        return {
            "car": self.index,
            "ai": self.ai,
            "laps_completed": len(self.laps),
            "laps": self.laps,
            "best_lap_ms": min(valid or timed) if timed else None,
            "mean_lap_ms": round(sum(timed) / len(timed)) if timed else None,
            "max_speed_kmh": round(self.max_speed, 2),
            "distance_m": round(self.distance, 1),
            "max_stuck_s": round(self.max_stuck, 1),
            "offtrack_s": round(self.offtrack, 1),
            "start_y": self.start_y,
            "min_y": self.min_y,
            "fell_m": round(self.start_y - self.min_y, 2) if self.start_y is not None else None,
        }


class Recorder:
    def __init__(self, out_dir=None, fmt="csv"):
        self.writer = None
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            ext = "csv" if fmt == "csv" else "jsonl"
            self.writer = Writer(os.path.join(out_dir, "telemetry.%s" % ext), fmt)
        self.cars = {}
        self.session = None
        self.cars_loaded = 0
        self.samples = 0

    def sample(self, t, snap):
        self.samples += 1
        self.session = snap.get("session") or self.session
        self.cars_loaded = max(self.cars_loaded, len(snap["cars"]))
        for c in snap["cars"]:
            if c is None:
                continue
            st = self.cars.setdefault(c["car"], CarStats(c["car"]))
            st.update(t, c)
            if self.writer:
                self.writer.row(t, c)

    def close(self):
        if self.writer:
            self.writer.close()

    def results(self, extra=None):
        out = {"cars_loaded": self.cars_loaded, "samples": self.samples,
               "session": self.session, "cars": [self.cars[k].summary() for k in sorted(self.cars)]}
        if self.session and self.session.get("order"):
            out["order"] = self.session["order"]
        if extra:
            out.update(extra)
        return out


def write_laps_csv(path, results):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["car", "lap", "ms", "valid", "cuts", "t"])
        for car in results["cars"]:
            for lap in car["laps"]:
                w.writerow([car["car"], lap["lap"], lap["ms"], int(bool(lap["valid"])), lap["cuts"],
                            lap["t"]])
