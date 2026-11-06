import hashlib
import struct

BUILDS = {
    "1.16.4": {
        "steam_build": 14923034,
        "pe": {"machine": 0x8664, "timestamp": 0x5A55E7A8,
               "size_of_image": (0x15E1000, 0x15AE000)},
        "sha256": {
            "0df569c840f8303f7018f7891085e3a4c22cf93fb19327c6a0b85325cea23fd1": "steam",
            "a0615cf661e2656154b432f9e8428e767a3999f9015db71a0184f69a07247b93": "steamless",
            "8e403de4188461f0a4236040c5893f6cab25f04dcce74fa7177edfa2847ab008": "steamless",
        },
        "rva": {
            "pyi": 0x1559AF0,
            "game_render": 0x242D50,
            "game_render_hud": 0x242E30,
            "display_mode": 0x1A8A0,
            "start_game": 0x19EB00,
            "start_race": 0x141470,
            "ai_ctor": 0x298C60,
            "ai_init_tyres": 0x29E600,
            "set_controller": 0x275A70,
            "ai_vftable": 0x4FBFD0,
        },
        "field": {
            "pyi_sim": 0x58,
            "sim_cars": 0x208,
            "sim_client": 0x1C8,
            "av_phys": 0x268,
            "av_car": 4456,
            "av_race_manager": 4584,
            "av_in_pitlane": 4764,
            "phys_world": 0x04,
            "phys_rpm": 0x244,
            "phys_steer": 0x25C,
            "phys_gas": 0x260,
            "phys_brake": 0x264,
            "phys_clutch": 0x268,
            "phys_gear": 0x26C,
            "phys_velocity": 0x274,
            "phys_turbo": 0x738,
            "phys_fuel": 0x794,
            "car_transponder": 504,
            "tt_last_lap": 4,
            "tt_best_lap": 8,
            "tt_lap_count": 12,
            "tt_last_valid": 17,
            "tt_splits": 48,
            "tt_cuts": 132,
            "car_spline": 15056,
            "sld_npos": 0,
            "sld_lateral": 8,
            "sld_off_track": 36,
            "car_controls_provider": 15744,
            "car_tyres": 2856,
            "tyre_stride": 2136,
            "tyre_compound": 1608,
            "tyre_defs": 1280,
            "compound_def_size": 0x3F0,
            "car_ai_laps": 15480,
            "ai_size": 1000,
            "ai_pref_compound": 732,
            "rm_clock": 8,
            "clock_ms": 0x18,
            "rm_session_index": 164,
            "rm_session_type": 232,
            "rm_session_laps": 240,
            "rm_start_time": 320,
            "rm_is_over": 332,
            "rm_sim": 360,
            "rm_realtime_pos": 416,
            "rt_entry_size": 16,
        },
    }
}

DLL_NAMES = (
    "pyi", "game_render", "game_render_hud", "display_mode", "start_game", "start_race",
    "ai_ctor", "ai_init_tyres", "set_controller", "pyi_sim", "sim_cars", "sim_client",
    "av_phys", "av_car", "av_race_manager", "phys_rpm", "car_tyres", "tyre_compound",
    "tyre_defs", "compound_def_size", "car_ai_laps", "ai_pref_compound", "rm_clock",
    "clock_ms", "rm_session_type", "rm_start_time", "rm_sim",
)


class UnknownBuild(Exception):
    pass


def pe_fingerprint(data):
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise UnknownBuild("not a Windows executable")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if pe + 24 + 60 > len(data) or data[pe:pe + 4] != b"PE\0\0":
        raise UnknownBuild("no PE header")
    machine = struct.unpack_from("<H", data, pe + 4)[0]
    timestamp = struct.unpack_from("<I", data, pe + 8)[0]
    size_of_image = struct.unpack_from("<I", data, pe + 24 + 56)[0]
    return {"machine": machine, "timestamp": timestamp, "size_of_image": size_of_image}


def identify(exe_path):
    with open(exe_path, "rb") as fh:
        head = fh.read(4096)
        fh.seek(0)
        digest = hashlib.sha256()
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return identify_bytes(head, digest.hexdigest())


def identify_bytes(head, sha256):
    fp = pe_fingerprint(head)
    for version, build in BUILDS.items():
        if sha256 in build["sha256"]:
            return version, build["sha256"][sha256]
    for version, build in BUILDS.items():
        pe = build["pe"]
        if (fp["machine"] == pe["machine"] and fp["timestamp"] == pe["timestamp"]
                and fp["size_of_image"] in pe["size_of_image"]):
            return version, "matching header"
    raise UnknownBuild(
        "acs.exe is not a build this tool knows (timestamp 0x%08X, image size 0x%X). "
        "Supported: %s" % (fp["timestamp"], fp["size_of_image"],
                           ", ".join("AC %s (Steam build %d)" % (v, b["steam_build"])
                                     for v, b in BUILDS.items())))


class Offsets:
    def __init__(self, version):
        build = BUILDS[version]
        self.version = version
        self.rva = dict(build["rva"])
        self.field = dict(build["field"])

    def __getattr__(self, name):
        table = self.__dict__.get("field", {})
        if name in table:
            return table[name]
        rva = self.__dict__.get("rva", {})
        if name in rva:
            return rva[name]
        raise AttributeError(name)

    def dll_env(self):
        merged = dict(self.rva)
        merged.update(self.field)
        return ",".join("%s=%x" % (k, merged[k]) for k in DLL_NAMES)


def for_exe(exe_path):
    version, _ = identify(exe_path)
    return Offsets(version)
