import os

SESSION_IDS = {"practice": 1, "qualify": 2, "race": 3, "hotlap": 4}


def first_skin(ac_dir, car):
    skins = os.path.join(ac_dir, "content", "cars", car, "skins")
    if os.path.isdir(skins):
        for name in sorted(os.listdir(skins)):
            if os.path.isdir(os.path.join(skins, name)):
                return name
    return ""


def check_content(ac_dir, track, layout, cars):
    problems = []
    tdir = os.path.join(ac_dir, "content", "tracks", track)
    if not os.path.isdir(tdir):
        problems.append("track not found: %s" % track)
    elif layout and not os.path.isdir(os.path.join(tdir, layout)):
        problems.append("layout not found: %s/%s" % (track, layout))
    for car in sorted(set(cars)):
        if not os.path.isdir(os.path.join(ac_dir, "content", "cars", car)):
            problems.append("car not found: %s" % car)
    return problems


def build(track, car, layout="", session="practice", laps=5, minutes=30, ai=0,
          ai_level=100, ai_aggression=0, ai_cars=None, skins=None, player_name="achl",
          starting_position=1, ambient=22, road=28, weather="3_clear", sun_angle=-10,
          time_mult=1, grip=100, fuel_rate=1, tyre_wear=1, damage=0, penalties=0,
          fixed_setup=0, spawn=None):
    if session not in SESSION_IDS:
        raise ValueError("unknown session %r" % session)
    total = 1 + int(ai)
    ai_cars = list(ai_cars or [])
    skins = dict(skins or {})
    models = [car] + [ai_cars[(i - 1) % len(ai_cars)] if ai_cars else car
                      for i in range(1, total)]
    race_laps = laps if session == "race" else 0
    sections = [
        ("HEADER", [("VERSION", 2)]),
        ("RACE", [("TRACK", track), ("CONFIG_TRACK", layout), ("MODEL", car),
                  ("MODEL_CONFIG", ""), ("SKIN", skins.get(car, "")), ("CARS", total),
                  ("AI_LEVEL", ai_level), ("AI_AGGRESSION", ai_aggression),
                  ("RACE_LAPS", race_laps), ("DRIFT_MODE", 0), ("FIXED_SETUP", fixed_setup),
                  ("PENALTIES", penalties), ("JUMP_START_PENALTY", 0),
                  ("FUEL_RATE", fuel_rate), ("TYRE_WEAR_RATE", tyre_wear),
                  ("DAMAGE_MULTIPLIER", damage)]),
        ("REMOTE", [("ACTIVE", 0)]),
        ("REPLAY", [("ACTIVE", 0)]),
        ("CAR_0", [("MODEL", "-"), ("MODEL_CONFIG", ""), ("SKIN", skins.get(car, "")),
                   ("SETUP", ""), ("DRIVER_NAME", player_name), ("NATIONALITY", ""),
                   ("NATION_CODE", ""), ("BALLAST", 0), ("RESTRICTOR", 0)]),
    ]
    for i in range(1, total):
        m = models[i]
        sections.append(("CAR_%d" % i, [
            ("MODEL", m), ("MODEL_CONFIG", ""), ("SKIN", skins.get(m, "")), ("SETUP", ""),
            ("DRIVER_NAME", "AI %d" % i), ("NATIONALITY", ""), ("NATION_CODE", ""),
            ("AI_LEVEL", ai_level), ("AI_AGGRESSION", ai_aggression), ("BALLAST", 0),
            ("RESTRICTOR", 0)]))
    s = [("NAME", session.capitalize()), ("TYPE", SESSION_IDS[session])]
    if session == "race":
        s += [("LAPS", laps), ("STARTING_POSITION", starting_position),
              ("SPAWN_SET", spawn or "START")]
    else:
        s += [("DURATION_MINUTES", minutes), ("SPAWN_SET", spawn or "PIT")]
    sections.append(("SESSION_0", s))
    sections += [
        ("LAP_INVALIDATOR", [("ALLOWED_TYRES_OUT", -1)]),
        ("GROOVE", [("VIRTUAL_LAPS", 10), ("MAX_LAPS", 1), ("STARTING_LAPS", 1)]),
        ("GHOST_CAR", [("RECORDING", 0), ("PLAYING", 0), ("ENABLED", 0), ("LOAD", 0),
                       ("FILE", ""), ("SECONDS_ADVANTAGE", 0)]),
        ("TEMPERATURE", [("AMBIENT", ambient), ("ROAD", road)]),
        ("WEATHER", [("NAME", weather)]),
        ("LIGHTING", [("SUN_ANGLE", sun_angle), ("TIME_MULT", time_mult),
                      ("CLOUD_SPEED", 0.2)]),
        ("DYNAMIC_TRACK", [("SESSION_START", grip), ("RANDOMNESS", 0), ("LAP_GAIN", 0),
                           ("SESSION_TRANSFER", 100)]),
        ("WIND", [("SPEED_KMH_MIN", 0), ("SPEED_KMH_MAX", 0), ("DIRECTION_DEG", 0)]),
    ]
    return render(sections)


def render(sections):
    out = []
    for name, items in sections:
        out.append("[%s]" % name)
        out += ["%s=%s" % (k, v) for k, v in items]
        out.append("")
    return "\n".join(out)


def parse(text):
    data, current = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = data.setdefault(line[1:-1], {})
        elif "=" in line and current is not None:
            k, v = line.split("=", 1)
            current[k.strip()] = v.strip()
    return data


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(text)
