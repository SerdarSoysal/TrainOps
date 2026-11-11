"""The switcher's yard jobs, worked out from the records (spec Sections 8, 9, 12).

Nothing here is stored: each job is derived from where the cars are now, so
the signal that completes a job and the work list that shows it always agree.

- Job A (Westbound manifest at the yard): cut the Local block (the manifest's
  cars assigned to a spot) into the Locals track; pick up the Westbound track.
- Job B (after the local): route every car the local brought back, and send
  home cars on the Locals track that are no longer held (confirmed 2026-11-11).
- Job C (Eastbound manifest at the yard): cut its Local block into the Locals
  track; pick up the Eastbound track.

Pick-up blocks are never left behind, except as a safeguard when the
destination (West staging, or the East loop) would overflow: then the oldest
pick-up cars go and the rest wait for tomorrow (spec Section 9).
"""

from __future__ import annotations

from dataclasses import dataclass

from trainops import vocab as v
from trainops.config import Config
from trainops.db import Car, Database
from trainops.planning import outgoing_types


@dataclass(frozen=True)
class YardJob:
    train: str
    cut: tuple[Car, ...]  # the rear Local block -> Locals track
    pickup: tuple[Car, ...]  # from the pick-up track -> added to the rear
    left_behind: tuple[Car, ...]  # pick-up cars that wait (overflow safeguard only)
    length_after: int  # cars in the train when it leaves the yard
    overload: bool  # an exception overload train


@dataclass(frozen=True)
class Move:
    """Job B: one car to one yard track, with the reason in plain words."""

    car: Car
    track: str
    reason: str


def job_a(db: Database, config: Config) -> YardJob:
    west_now = len(db.cars_at(v.AT_WORLD, v.WEST_STAGING))
    west_now += len(db.cars_at(v.AT_TRAIN, v.EASTBOUND_MANIFEST))  # still in West staging
    return _yard_job(
        db, config, v.WESTBOUND_MANIFEST, v.WESTBOUND_TRACK,
        config.settings.capacity.west_staging - west_now,
    )


def job_c(db: Database, config: Config) -> YardJob:
    east_now = len(db.cars_at(v.AT_WORLD, v.EAST_STAGING))
    return _yard_job(
        db, config, v.EASTBOUND_MANIFEST, v.EASTBOUND_TRACK,
        config.settings.capacity.east_staging - east_now,
    )


def job_b(db: Database, config: Config) -> list[Move]:
    """Where job B puts each car: the local's cars, then cars leaving the Locals track."""
    held_types = outgoing_types(config)
    hold_days = config.settings.hold_days_on_locals

    def holdable(car: Car) -> bool:
        return car.load == v.EMPTY and any(v.same_words(car.type, t) for t in held_types)

    moves = []
    for car in db.cars_at(v.AT_TRAIN, v.LOCAL):
        if car.bad_order:
            moves.append(Move(car, v.WESTBOUND_TRACK,
                              "bad order, leaves the roster at West staging"))
        elif car.assigned_spot is not None:
            moves.append(Move(car, v.LOCALS_TRACK, "not delivered, retry next run"))
        elif car.load == v.LOADED:
            world = car.dest_world or car.origin_world
            moves.append(Move(car, toward(world), f"loaded, to {world}"))
        elif holdable(car) and hold_days > 0:
            moves.append(Move(car, v.LOCALS_TRACK, "empty, held for reuse"))
        else:
            moves.append(Move(car, toward(car.origin_world),
                              f"empty, returning to {car.origin_world}"))
    for car in db.cars_at(v.AT_YARD, v.LOCALS_TRACK):
        if car.assigned_spot is not None:
            continue
        if holdable(car) and car.days_held <= hold_days:
            continue
        reason = "held too long" if holdable(car) else "not needed"
        moves.append(Move(car, toward(car.origin_world),
                          f"{car.load.lower()}, {reason}, returning to {car.origin_world}"))
    return moves


def toward(world: str) -> str:
    """The yard track for cars going to a world."""
    return v.EASTBOUND_TRACK if world == v.EAST_STAGING else v.WESTBOUND_TRACK


def _yard_job(db: Database, config: Config, train: str, track: str, room: int) -> YardJob:
    cars = db.cars_at(v.AT_TRAIN, train)
    cut = tuple(c for c in cars if c.assigned_spot is not None)
    after_cut = len(cars) - len(cut)
    waiting = db.cars_at(v.AT_YARD, track)  # oldest first
    taken = max(0, room - after_cut)
    pickup, left = tuple(waiting[:taken]), tuple(waiting[taken:])
    length = after_cut + len(pickup)
    return YardJob(train, cut, pickup, left, length,
                   length > config.settings.train_nominal_max)
