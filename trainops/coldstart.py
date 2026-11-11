"""Cold start (spec Section 14): start the railroad over from the roster files.

Both files are checked completely first; if anything is wrong nothing is
changed. Otherwise, in one transaction, everything is cleared and the
railroad starts again at day 1:
- every car is put in the world its location names, with load "Not tracked"
  and that world as its origin
- every engine is put in Storage or the world its location names
- every spot is awaiting a car (a random spot draws its first requirement)
  and gets its day-early rolls
- the yard is empty

(Planning the first session's trains comes with train planning, step 7.)
"""

from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

from trainops import vocab as v
from trainops.config import Config
from trainops.db import Database
from trainops.reconcile import create_spot_states
from trainops.spots import roll_ahead
from trainops.rosterfiles import (
    RosterFileError,
    engine_count_problems,
    read_cars,
    read_engines,
)


def cold_start(
    db: Database,
    config: Config,
    cars_path: str | Path,
    engines_path: str | Path,
    rng: random.Random | None = None,
) -> list[str]:
    """Clear everything and import the roster files. Returns plain-language notes.

    Raises RosterFileError (and changes nothing) if either file has problems.
    `rng` is for repeatable tests; normally left out.
    """
    rng = rng or random.Random()
    cars_path, engines_path = Path(cars_path), Path(engines_path)
    cars, problems = read_cars(cars_path)
    engines, engine_problems = read_engines(engines_path)
    problems += engine_problems

    per_world = Counter(car.location for car in cars)
    capacity = config.settings.capacity
    for world, limit in ((v.EAST_STAGING, capacity.east_staging), (v.WEST_STAGING, capacity.west_staging)):
        if per_world[world] > limit:
            problems.append(
                f"{cars_path.name}: {per_world[world]} cars are in {world}, "
                f"but it holds {limit}"
            )
    if not engine_problems:
        problems += engine_count_problems([e.pool for e in engines], engines_path.name)
    if problems:
        raise RosterFileError(problems)

    with db.transaction():
        db.clear_all()
        for car in cars:
            db.add_car(
                mark=car.mark,
                number=car.number,
                type=car.type,
                loc_kind=v.AT_WORLD,
                loc_ref=car.location,
                origin_world=car.location,
            )
        for engine in engines:
            db.add_engine(
                mark=engine.mark,
                number=engine.number,
                model=engine.model,
                pool=engine.pool,
                loc_kind=v.AT_STORAGE if engine.location == v.STORAGE else v.AT_WORLD,
                loc_ref=engine.location,
            )
        create_spot_states(db, config)
        for spot in config.spots:
            state = db.spot_state(spot.spot_id)
            db.put_spot_state(roll_ahead(spot, state, rng, config.settings))

    notes = [
        f"Cold start done: {len(cars)} cars ({per_world[v.EAST_STAGING]} in East staging, "
        f"{per_world[v.WEST_STAGING]} in West staging), {len(engines)} engines, "
        f"{len(config.spots)} spots awaiting cars. Day 1 begins."
    ]
    notes += _unserved_spot_notes(config, cars)
    return notes


def _unserved_spot_notes(config: Config, cars) -> list[str]:
    """Warn about spots that no car in the roster can ever serve."""
    notes = []
    for spot in config.spots:
        if spot.fixed:
            types = [spot.fixed.car_type]
        else:
            types = [r.car_type for r in spot.possible_requirements]
        for car_type in types:
            if not any(v.same_words(car.type, car_type) for car in cars):
                notes.append(f"Warning: no car in the roster can serve {spot.label} ({car_type}).")
    return notes
