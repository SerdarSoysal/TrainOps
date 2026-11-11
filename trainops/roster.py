"""Roster changes after the cold start (agreed 2026-11-11).

Retiring a car:
- at an industry spot: the car is marked Bad order. The local pulls it, job B
  sends it west, and it leaves the roster when it reaches West staging. (The
  pull, routing and arrival are handled with the signals, steps 7-8.)
- anywhere else: removed at once; take it off the layout. If it was planned
  into a train, that train runs one car short.
Retiring an engine: removed at once (engines are never at spots).

Syncing the roster: cars.csv and engines.csv are compared with the database.
- a car or engine new in a file is added (new cars go into West staging only:
  East staging holds exactly the last Eastbound manifest)
- one missing from a file is retired, as above
- an existing car keeps its place; its type can never change
- an existing engine takes the file's pool and model
Nothing is changed if any problem is found.
"""

from __future__ import annotations

from pathlib import Path

from trainops import vocab as v
from trainops.config import Config
from trainops.db import Car, Database, Engine
from trainops.rosterfiles import (
    RosterFileError,
    engine_count_problems,
    read_cars,
    read_engines,
)


def where_is(config: Config, loc_kind: str, loc_ref: str) -> str:
    """A location in plain words: "East staging", "Northfield Paper, Loading door 1"."""
    if loc_kind == v.AT_SPOT:
        spot = config.spots_by_id.get(loc_ref)
        return spot.label if spot else f"the spot with id '{loc_ref}'"
    return loc_ref


def retire_car(db: Database, config: Config, car: Car) -> str:
    """Retire one car (call inside a transaction). Returns a plain-language note."""
    if car.loc_kind == v.AT_SPOT:
        place = where_is(config, car.loc_kind, car.loc_ref)
        if car.bad_order:
            return f"Car {car.label} at {place} is already marked Bad order."
        db.update_car(car.id, bad_order=True)
        return (
            f"Car {car.label} at {place} is marked Bad order: the local will pull it "
            f"and it leaves the roster at West staging."
        )
    place = where_is(config, car.loc_kind, car.loc_ref)
    db.remove_from_consist_plans(car_id=car.id)
    db.remove_car(car.id)
    return f"Car {car.label} retired — take it off the layout ({place})."


def retire_engine(db: Database, engine: Engine) -> str:
    """Retire one engine (call inside a transaction). Returns a plain-language note."""
    db.remove_from_consist_plans(engine_id=engine.id)
    db.remove_engine(engine.id)
    return f"Engine {engine.label} retired — take it off the layout ({engine.loc_ref})."


def sync_roster(
    db: Database, config: Config, cars_path: str | Path, engines_path: str | Path
) -> list[str]:
    """Bring the roster in line with the two files, in one transaction.

    Raises RosterFileError (and changes nothing) if anything is wrong.
    Returns plain-language notes on what changed.
    """
    cars_path, engines_path = Path(cars_path), Path(engines_path)
    car_rows, problems = read_cars(cars_path)
    engine_rows, engine_problems = read_engines(engines_path)
    problems += engine_problems
    if problems:
        raise RosterFileError(problems)

    cars = {(c.mark.upper(), c.number): c for c in db.cars()}
    engines = {(e.mark.upper(), e.number): e for e in db.engines()}

    new_cars = []
    for row in car_rows:
        car = cars.get(row.key)
        where = f"{cars_path.name}, line {row.line}"
        if car is None:
            if row.location != v.WEST_STAGING:
                problems.append(
                    f"{where}: new car {row.label} can only be added to West staging "
                    f"(East staging holds exactly the last Eastbound manifest)"
                )
            new_cars.append(row)
        elif not v.same_words(car.type, row.type):
            problems.append(
                f"{where}: {row.label} is a {car.type} in the roster but '{row.type}' in the "
                f"file — a car's type can't be changed"
            )

    in_west = sum(1 for c in cars.values() if c.loc_kind == v.AT_WORLD and c.loc_ref == v.WEST_STAGING)
    room = config.settings.capacity.west_staging - in_west
    if len(new_cars) > room:
        problems.append(
            f"{cars_path.name}: {len(new_cars)} new cars won't fit in West staging "
            f"(room for {max(room, 0)})"
        )

    engine_keys = {row.key for row in engine_rows}
    problems += engine_count_problems([row.pool for row in engine_rows], engines_path.name)
    if problems:
        raise RosterFileError(problems)

    car_keys = {row.key for row in car_rows}
    notes: list[str] = []
    with db.transaction():
        for row in new_cars:
            db.add_car(
                mark=row.mark,
                number=row.number,
                type=row.type,
                loc_kind=v.AT_WORLD,
                loc_ref=v.WEST_STAGING,
                origin_world=v.WEST_STAGING,
            )
            notes.append(f"Car {row.label} ({row.type}) added to West staging.")
        for key, car in cars.items():
            if key not in car_keys and not car.bad_order:
                notes.append(retire_car(db, config, car))

        for row in engine_rows:
            engine = engines.get(row.key)
            if engine is None:
                loc_kind = v.AT_STORAGE if row.location == v.STORAGE else v.AT_WORLD
                db.add_engine(
                    mark=row.mark,
                    number=row.number,
                    model=row.model,
                    pool=row.pool,
                    loc_kind=loc_kind,
                    loc_ref=row.location,
                )
                notes.append(f"Engine {row.label} added to {row.location}.")
                continue
            changes = {}
            if engine.pool != row.pool:
                changes["pool"] = row.pool
                notes.append(f"Engine {row.label} moved from the {engine.pool.lower()} pool "
                             f"to the {row.pool.lower()} pool.")
            if (engine.model or None) != row.model:
                changes["model"] = row.model
                notes.append(f"Engine {row.label} model changed to {row.model or '(none)'}.")
            if changes:
                db.update_engine(engine.id, **changes)
        for key, engine in engines.items():
            if key not in engine_keys:
                notes.append(retire_engine(db, engine))

    return notes or ["The roster already matches the files; nothing changed."]
