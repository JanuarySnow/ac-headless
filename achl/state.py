import math
import struct

from .memory import ReadError

SESSION_TYPES = {1: "practice", 2: "qualify", 3: "race", 4: "hotlap", 5: "time_attack",
                 6: "drift", 7: "drag"}


def lap_ms(v):
    return v if isinstance(v, int) and 0 < v < 3600000 else None


def fmt_ms(v):
    v = lap_ms(v)
    if v is None:
        return "-"
    return "%d:%02d.%03d" % (v // 60000, (v // 1000) % 60, v % 1000)


class Game:
    def __init__(self, reader, offsets):
        self.r = reader
        self.o = offsets
        self.base = reader.base

    def _sim(self):
        o, r = self.o, self.r
        pyi = r.u64(self.base + o.pyi)
        if not pyi:
            return 0
        return r.u64(pyi + o.pyi_sim)

    def avatars(self):
        o, r = self.o, self.r
        try:
            sim = self._sim()
            if not sim:
                return []
            begin, end = r.u64(sim + o.sim_cars), r.u64(sim + o.sim_cars + 8)
            if not begin or end <= begin or end - begin > 8 * 512:
                return []
            return [r.u64(begin + 8 * i) for i in range((end - begin) // 8)]
        except ReadError:
            return []

    def loaded(self):
        return bool(self.avatars())

    def session(self, avatars=None):
        o, r = self.o, self.r
        avatars = avatars if avatars is not None else self.avatars()
        if not avatars:
            return None
        rm = r.u64(avatars[0] + o.av_race_manager)
        if not rm:
            return None
        stype = r.i32(rm + o.rm_session_type)
        holder = r.u64(rm + o.rm_clock)
        clock = r.f64(holder + o.clock_ms) if holder else float("nan")
        start = r.f64(rm + o.rm_start_time)
        return {
            "type": SESSION_TYPES.get(stype, str(stype)),
            "type_id": stype,
            "index": r.i32(rm + o.rm_session_index),
            "laps": r.i32(rm + o.rm_session_laps),
            "clock_ms": clock,
            "start_ms": None if start > 1e300 else start,
            "over": bool(r.u8(rm + o.rm_is_over)),
            "order": self._order(rm, avatars),
        }

    def _order(self, rm, avatars):
        o, r = self.o, self.r
        index = {a: i for i, a in enumerate(avatars)}
        vb, ve = r.u64(rm + o.rm_realtime_pos), r.u64(rm + o.rm_realtime_pos + 8)
        out = []
        if vb and ve > vb and ve - vb <= o.rt_entry_size * 512:
            for k in range((ve - vb) // o.rt_entry_size):
                i = index.get(r.u64(vb + k * o.rt_entry_size))
                if i is not None:
                    out.append(i)
        return out

    def car(self, avatar, index=0):
        o, r = self.o, self.r
        phys = avatar + o.av_phys
        car = r.u64(avatar + o.av_car)
        world = r.read(phys + o.phys_world, 64)
        m = struct.unpack("<16f", world)
        vx, vy, vz = r.vec3(phys + o.phys_velocity)
        tt = car + o.car_transponder
        sld = car + o.car_spline
        prov = r.u64(car + o.car_controls_provider)
        is_ai = bool(prov) and r.u64(prov) == self.base + o.ai_vftable
        return {
            "car": index,
            "pos": [m[12], m[13], m[14]],
            "speed_kmh": math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6,
            "rpm": r.f32(phys + o.phys_rpm),
            "gear": r.i32(phys + o.phys_gear),
            "gas": r.f32(phys + o.phys_gas),
            "brake": r.f32(phys + o.phys_brake),
            "steer": r.f32(phys + o.phys_steer),
            "fuel": r.f32(phys + o.phys_fuel),
            "npos": r.f32(sld + o.sld_npos),
            "lateral": r.f32(sld + o.sld_lateral),
            "off_track": bool(r.u8(sld + o.sld_off_track)),
            "in_pit": bool(r.u8(avatar + o.av_in_pitlane)),
            "laps": r.i32(tt + o.tt_lap_count),
            "last_lap_ms": lap_ms(r.i32(tt + o.tt_last_lap)),
            "best_lap_ms": lap_ms(r.i32(tt + o.tt_best_lap)),
            "last_lap_valid": bool(r.u8(tt + o.tt_last_valid)),
            "cuts": r.i32(tt + o.tt_cuts),
            "tyre_compound": r.i32(car + o.car_tyres + o.tyre_compound),
            "ai": is_ai,
        }

    def snapshot(self):
        avatars = self.avatars()
        if not avatars:
            return None
        cars = []
        for i, a in enumerate(avatars):
            try:
                cars.append(self.car(a, i))
            except ReadError:
                cars.append(None)
        try:
            session = self.session(avatars)
        except ReadError:
            session = None
        return {"session": session, "cars": cars}
