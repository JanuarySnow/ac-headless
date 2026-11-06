import os
import shutil

VIDEO = [
    ("VIDEO", [("AAQUALITY", 0), ("AASAMPLES", 1), ("ANISOTROPIC", 0), ("DISABLE_LEGACY_HDR", 1),
               ("FPS_CAP_MS", 0), ("FULLSCREEN", 0), ("HEIGHT", 240), ("INDEX", 0),
               ("REFRESH", 60), ("SHADOW_MAP_SIZE", 0), ("VSYNC", 0), ("WIDTH", 320)]),
    ("ASSETTOCORSA", [("HIDE_ARMS", 1), ("HIDE_STEER", 1), ("LOCK_STEER", 0), ("WORLD_DETAIL", 0)]),
    ("CAMERA", [("MODE", "DEFAULT")]),
    ("CUBEMAP", [("FACES_PER_FRAME", 0), ("FARPLANE", 100), ("SIZE", 0)]),
    ("EFFECTS", [("FXAA", 0), ("MOTION_BLUR", 0), ("RENDER_SMOKE_IN_MIRROR", 0), ("SMOKE", 0),
                 ("SMOKE_IN_MIRROR", 0)]),
    ("MIRROR", [("HQ", 0), ("SIZE", 0)]),
    ("POST_PROCESS", [("DOF", 0), ("ENABLED", 0), ("FILTER", "default"), ("FXAA", 0), ("GLARE", 0),
                      ("HEAT_SHIMMER", 0), ("QUALITY", 0), ("RAYS_OF_GOD", 0)]),
    ("SATURATION", [("LEVEL", 100)]),
]

REPLAY = [
    ("REPLAY", [("MAX_SIZE_MB", 1)]),
    ("QUALITY", [("LEVEL", 0)]),
    ("AUTOSAVE", [("ENABLED", 0), ("RACE", 0), ("QUALIFY", 0), ("OTHERS", 0),
                  ("MIN_TIME_SECONDS", 99999)]),
]

AUDIO = [
    ("HEADER", [("VERSION", 1)]),
    ("LEVELS", [(k, 0) for k in ("MASTER", "ENGINE", "WIND", "TYRES", "OPPONENTS", "MUSIC",
                                 "UISOUNDS", "SURFACES", "DIRT_BOTTOM", "BRAKES")]),
]

ASSISTS = [
    ("ASSISTS", [("IDEAL_LINE", 0), ("AUTO_BLIP", 1), ("STABILITY_CONTROL", 0), ("AUTO_BRAKE", 0),
                 ("AUTO_SHIFTER", 1), ("AUTO_CLUTCH", 1)]),
]


def _ini(sections):
    out = []
    for name, items in sections:
        out.append("[%s]" % name)
        out += ["%s=%s" % (k, v) for k, v in items]
        out.append("")
    return "\n".join(out)


def build(root, race_ini_text, video_width=320, video_height=240):
    ac = os.path.join(root, "Assetto Corsa")
    if os.path.isdir(ac):
        shutil.rmtree(ac)
    cfg = os.path.join(ac, "cfg")
    for sub in ("cfg", "logs", os.path.join("replay", "temp"), "setups", "screenshots",
                "personalbest", "out"):
        os.makedirs(os.path.join(ac, sub), exist_ok=True)
    video = [(n, [(k, video_width if k == "WIDTH" else video_height if k == "HEIGHT" else v)
                  for k, v in items]) for n, items in VIDEO]
    files = {"video.ini": _ini(video), "replay.ini": _ini(REPLAY), "audio.ini": _ini(AUDIO),
             "assists.ini": _ini(ASSISTS), "race.ini": race_ini_text}
    for name, text in files.items():
        with open(os.path.join(cfg, name), "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(text)
    return ac


def game_log(root):
    return os.path.join(root, "Assetto Corsa", "logs", "log.txt")
