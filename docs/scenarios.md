# Scenario files

A scenario is a JSON file with a `run` object, which takes the same settings as `achl run`, and a list of checks under `assert`.

```json
{
  "name": "hotlap",
  "run": {"mode": "hotlap", "track": "magione", "car": "bmw_m3_e30", "laps": 3, "timeout": 900},
  "assert": [
    {"check": "laps_completed", "car": 0, "min": 3},
    {"check": "best_lap", "car": 0, "min_ms": 80000, "max_ms": 110000}
  ]
}
```

`name` defaults to the file name. Each scenario gets its own folder in the output folder.

## Run settings

`mode`, `track`, `layout`, `car`, `ai`, `ai_cars` (a list), `ai_level`, `ai_aggression`, `laps`, `minutes`, `timeout`, `render`, `hz`, `format`, `drive` (true or false), `grip`, `ambient`, `road`, `weather`, `fuel_rate`, `tyre_wear`, `damage`, `spawn` (`PIT` or `START`), `starting_position`, `player_name`, `load_timeout`, `start_delay_ms`, `memory_max`.

Unknown settings are an error, so a typo does not go unnoticed.

## Picking cars

Most checks take `car`: a car number (0 is your car, AI opponents are 1 and up), `"ai"` for every opponent, or `"all"`. The default is 0.

## Checks

| check | settings | passes when |
|---|---|---|
| `outcome` | `is` (default `ok`) | the run ended this way. Added automatically if you leave it out |
| `cars_loaded` | `min` (default 1 + `ai`) | at least this many cars were in the session |
| `laps_completed` | `min` (default `laps`) | each car finished this many laps |
| `best_lap` | `min_ms`, `max_ms` | each car's best lap is in range. Valid laps count first |
| `max_speed` | `min_kmh`, `max_kmh` | each car's top speed is in range |
| `no_stuck` | `max_seconds` (15) | no car stood still outside the pits for longer than this, once it had moved |
| `offtrack` | `max_seconds` (5) | no car spent longer than this outside track limits, not counting time in the pit lane |
| `no_fall` | `max_drop_m` (20) | no car dropped further than this below where it spawned. Catches falling through the world |
| `moved` | `min_m` (50) | each car covered at least this distance |
| `lap_time_regression` | `baseline`, `tolerance_pct` (1.0), `write_missing` (true) | each car's best lap is within the tolerance of the baseline file |

For `lap_time_regression` the baseline path is relative to the scenario file. If the file does not exist it is written from this run and the check passes, so the first run sets the baseline. Delete the file to take a new one.

## Telemetry columns

`t` (seconds since the car started driving), `car`, `laps`, `npos` (0 to 1 around the lap), `speed_kmh`, `rpm`, `gear`, `gas`, `brake`, `steer`, `fuel`, `x`, `y`, `z`, `in_pit`, `off_track`, `tyre_compound`.

## The examples

- `hotlap.json`: three AI laps at Magione in the BMW M3 E30, lap time in a sane range, no stops, no time off track.
- `ai-race.json`: a ten car race at Brands Hatch Indy in the MX-5 Cup, everyone finishes four laps, nobody stuck.
- `pit-spawn-check.json`: eighteen cars spawn in Magione's pit boxes and drive out. Nobody falls through the floor, everyone moves.
- `lap-regression.json`: four laps, then the best lap is compared to `lap-regression.baseline.json`. Useful after editing a car's physics.
