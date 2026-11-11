"""Signals and the daily sequence (spec Sections 11 and 13).

`handle` is the single entry point for every signal, whatever sends it (the
web page now, ESP32 button nodes later). Each signal is one transaction:
either all of its changes are saved or, if it is refused, none.

Signals are taken in sequence order:
    West chore done, East chore done   (either order)
    Switch westbound done
    Pull done / Set-out done (per spot, any order; a set-out on an occupied
        spot waits for its pull)
    Local back in yard                 (skipped automatically if no local work)
    Local return job done
    Switch eastbound done
    Session complete                   (the day advance)
A signal for a later job while an earlier one is pending is refused with
"Waiting on ...". Undoing a mistaken signal is done with the edit tool.

What each signal changes:
- chores: each manifest is built in its world from the plan; engines not
  in the plan at that world go to Storage
- Switch westbound: Local block -> Locals track; Westbound track -> rear of train; the
  train reaches West staging (Bad order cars aboard leave the roster); the
  local is made up from its planned engines and cars
- pull: car -> local; outgoing spot's car is loaded for the destination
  fixed at Ready, incoming spot's car is empty; spot -> Idle or Awaiting car
- set-out: car -> spot, assignment cleared; spot -> Processing
- local back: closes the local; cars not set out are not delivered
- the Local return job: the local's cars sorted (yardwork.local_return); local engines -> Storage
- Switch eastbound: Local block -> Locals track; Eastbound track -> rear; the train
  reaches the East loop
- session complete: held empties count a day; every spot advances (frozen
  while it holds a Bad order car); the new day is planned
"""

from __future__ import annotations

import random

from trainops import spots
from trainops import vocab as v
from trainops.config import Config
from trainops.db import Car, Database, Session
from trainops.planning import plan_day
from trainops.yardwork import switch_westbound, local_return, switch_eastbound

# The session flags in sequence order, with how a refusal names each job.
_STEPS = (
    ("west_chore_done", "the West chore"),
    ("east_chore_done", "the East chore"),
    ("switch_westbound_done", "Switch westbound"),
    ("local_back", "the local"),
    ("local_return_done", "the Local return job"),
    ("switch_eastbound_done", "Switch eastbound"),
)
_FLAG_OF = {
    v.WEST_CHORE_DONE: "west_chore_done",
    v.EAST_CHORE_DONE: "east_chore_done",
    v.SWITCH_WESTBOUND_DONE: "switch_westbound_done",
    v.LOCAL_BACK: "local_back",
    v.LOCAL_RETURN_DONE: "local_return_done",
    v.SWITCH_EASTBOUND_DONE: "switch_eastbound_done",
}
_DONE_NAME = {
    "west_chore_done": "The West chore",
    "east_chore_done": "The East chore",
    "switch_westbound_done": "Switch westbound",
    "local_back": "The local",
    "local_return_done": "Local return job",
    "switch_eastbound_done": "Switch eastbound",
}


class SignalRefused(Exception):
    """A signal that can't be taken now; the message says why, in plain words."""


def current_job(session: Session) -> str:
    """The job the session is waiting on (what the page shows)."""
    if not (session.west_chore_done and session.east_chore_done):
        return v.JOB_CHORES
    for flag, job in (("switch_westbound_done", v.SWITCH_WESTBOUND), ("local_back", v.JOB_LOCAL),
                      ("local_return_done", v.LOCAL_RETURN), ("switch_eastbound_done", v.SWITCH_EASTBOUND)):
        if not getattr(session, flag):
            return job
    return v.JOB_END


def handle(
    db: Database,
    config: Config,
    signal: str,
    spot_id: str | None = None,
    rng: random.Random | None = None,
) -> list[str]:
    """Take one signal. Returns plain-language notes; raises SignalRefused."""
    name = v.match_word(signal, v.SIGNALS)
    if name is None:
        raise SignalRefused(f"'{signal}' is not a signal. Signals: {v.either(v.SIGNALS)}.")
    if name in v.SPOT_SIGNALS and spot_id not in config.spots_by_id:
        raise SignalRefused(f"{name} needs a spot; '{spot_id}' is not one.")
    with db.transaction():
        _check_order(db.session(), name)
        return _EFFECTS[name](db, config, spot_id, rng or random.Random())


# --- order -----------------------------------------------------------------------------


def _check_order(session: Session, name: str) -> None:
    flag = _FLAG_OF.get(name)
    if flag is not None and getattr(session, flag):
        raise SignalRefused(f"{_DONE_NAME[flag]} is already done.")
    if name in v.SPOT_SIGNALS and session.local_back:
        raise SignalRefused("The local is already back in the yard.")

    if name in (v.WEST_CHORE_DONE, v.EAST_CHORE_DONE):
        needed = 0
    elif name == v.SWITCH_WESTBOUND_DONE:
        needed = 2
    elif name in v.SPOT_SIGNALS or name == v.LOCAL_BACK:
        needed = 3
    elif name == v.SESSION_COMPLETE:
        needed = len(_STEPS)
    else:
        needed = [f for f, _ in _STEPS].index(flag)
    pending = [job for f, job in _STEPS[:needed] if not getattr(session, f)]
    if pending:
        chores = [j for j in pending if "chore" in j]
        raise SignalRefused(f"Waiting on {v.both(chores or pending[:1])}.")


# --- the chores ------------------------------------------------------------------------


def _west_chore(db, config, spot_id, rng):
    db.update_session(west_chore_done=True)
    return _build_manifest(db, v.EASTBOUND_MANIFEST, v.WEST_STAGING)


def _east_chore(db, config, spot_id, rng):
    db.update_session(east_chore_done=True)
    notes = _build_manifest(db, v.WESTBOUND_MANIFEST, v.EAST_STAGING)
    for car in db.cars_at(v.AT_WORLD, v.EAST_STAGING):
        notes.append(f"{car.label} is still in East staging but isn't in the "
                     f"westbound manifest's plan.")
    return notes


def _build_manifest(db: Database, train: str, world: str) -> list[str]:
    """Make up a manifest in its world from the plan; spare engines go to Storage."""
    notes = []
    planned_engines = set()
    for entry in db.consist_plan(train):
        if entry.engine_id is not None:
            engine = db.engine(entry.engine_id)
            planned_engines.add(engine.id)
            if engine.loc_kind == v.AT_STORAGE or engine.loc_ref == world:
                db.update_engine(engine.id, loc_kind=v.AT_TRAIN, loc_ref=train, seq=entry.seq)
            else:
                notes.append(f"Engine {engine.label} is not in {world} or Storage; "
                             f"left out of the {train.lower()}.")
        else:
            car = db.car(entry.car_id)
            if car.loc_kind == v.AT_WORLD and car.loc_ref == world:
                db.update_car(car.id, loc_kind=v.AT_TRAIN, loc_ref=train, seq=entry.seq)
            else:
                notes.append(f"{car.label} is not in {world}; left out of the {train.lower()}.")
    for engine in db.engines_at(v.AT_WORLD, world):
        if engine.id not in planned_engines:
            db.update_engine(engine.id, loc_kind=v.AT_STORAGE, loc_ref=v.STORAGE, seq=None)
    return notes


# --- Switch westbound and the local ---------------------------------------------------------------


def _switch_westbound(db, config, spot_id, rng):
    job = switch_westbound(db, config)
    for car in job.cut:
        _to_track(db, car, v.LOCALS_TRACK)
    for car in job.pickup:
        _to_train(db, car, v.WESTBOUND_MANIFEST)
    notes = _arrive(db, v.WESTBOUND_MANIFEST, v.WEST_STAGING)
    if job.left_behind:
        notes.append(f"{len(job.left_behind)} cars wait on the Westbound track "
                     f"(West staging is full).")
    db.update_session(switch_westbound_done=True)

    if _local_has_work(db, config):
        _make_up_local(db)
        db.update_session(local_has_work=True)
    else:
        db.update_session(local_has_work=False, local_back=True)
        notes.append("No work for the local today.")
    return notes


def _local_has_work(db: Database, config: Config) -> bool:
    planned = {e.car_id for e in db.consist_plan(v.LOCAL) if e.car_id is not None}
    on_locals = {c.id for c in db.cars_at(v.AT_YARD, v.LOCALS_TRACK)}
    if planned & on_locals:
        return True
    states = db.spot_states()
    for car in db.cars():
        if car.loc_kind == v.AT_SPOT and (
            car.bad_order or states[car.loc_ref].state == v.READY_FOR_PICKUP
        ):
            return True
    return False


def _make_up_local(db: Database) -> None:
    seq = 0
    for entry in db.consist_plan(v.LOCAL):
        seq += 1
        if entry.engine_id is not None:
            db.update_engine(entry.engine_id, loc_kind=v.AT_TRAIN, loc_ref=v.LOCAL, seq=seq)
        else:
            car = db.car(entry.car_id)
            if car.loc_kind == v.AT_YARD and car.loc_ref == v.LOCALS_TRACK:
                db.update_car(car.id, loc_kind=v.AT_TRAIN, loc_ref=v.LOCAL, seq=seq)


def _pull(db, config, spot_id, rng):
    spot = config.spot(spot_id)
    car = _car_at(db, spot_id)
    if car is None:
        raise SignalRefused(f"There is no car at {spot.label} to pull.")
    state = db.spot_state(spot_id)
    try:
        new_state = spots.pull(spot, state, db.session().day, bad_order=car.bad_order)
    except spots.SpotRuleError as problem:
        raise SignalRefused(str(problem)) from None
    changes = {}
    if not car.bad_order:
        if spots.need(spot, state).direction == v.OUTGOING:
            dest = v.EAST_STAGING if state.out_dest == v.EAST else v.WEST_STAGING
            changes = dict(load=v.LOADED, last_loaded_industry=spot.industry_id, dest_world=dest)
        else:
            changes = dict(load=v.EMPTY)
    _to_train(db, car, v.LOCAL, assigned_spot=None, **changes)
    db.put_spot_state(new_state)
    note = f"Pulled {car.label} from {spot.label}"
    return [note + (" (bad order)." if car.bad_order else ".")]


def _set_out(db, config, spot_id, rng):
    spot = config.spot(spot_id)
    car = next((c for c in db.cars_at(v.AT_TRAIN, v.LOCAL) if c.assigned_spot == spot_id), None)
    if car is None:
        raise SignalRefused(f"No car on the local is for {spot.label}.")
    occupant = _car_at(db, spot_id)
    if occupant is not None:
        raise SignalRefused(f"Pull {occupant.label} from {spot.label} first.")
    try:
        new_state = spots.set_out(spot, db.spot_state(spot_id))
    except spots.SpotRuleError as problem:
        raise SignalRefused(str(problem)) from None
    db.update_car(car.id, loc_kind=v.AT_SPOT, loc_ref=spot_id, seq=None,
                  assigned_spot=None, days_held=0)
    db.put_spot_state(new_state)
    return [f"Spotted {car.label} at {spot.label}."]


def _local_back(db, config, spot_id, rng):
    db.update_session(local_back=True)
    undelivered = [c for c in db.cars_at(v.AT_TRAIN, v.LOCAL) if c.assigned_spot]
    if not undelivered:
        return []
    return [f"Not delivered, back to the Locals track at the Local return job: "
            f"{v.both(c.label for c in undelivered)}."]


# --- jobs B and C ----------------------------------------------------------------------


def _local_return(db, config, spot_id, rng):
    for move in local_return(db, config):
        changes = {"days_held": 0} if move.car.loc_kind == v.AT_TRAIN and \
            move.track == v.LOCALS_TRACK and move.car.assigned_spot is None else {}
        _to_track(db, move.car, move.track, **changes)
    for engine in db.engines_at(v.AT_TRAIN, v.LOCAL):
        db.update_engine(engine.id, loc_kind=v.AT_STORAGE, loc_ref=v.STORAGE, seq=None)
    db.update_session(local_return_done=True)
    return []


def _switch_eastbound(db, config, spot_id, rng):
    job = switch_eastbound(db, config)
    for car in job.cut:
        _to_track(db, car, v.LOCALS_TRACK)
    for car in job.pickup:
        _to_train(db, car, v.EASTBOUND_MANIFEST)
    notes = _arrive(db, v.EASTBOUND_MANIFEST, v.EAST_STAGING)
    if job.left_behind:
        notes.append(f"{len(job.left_behind)} cars wait on the Eastbound track "
                     f"(the East loop is full).")
    db.update_session(switch_eastbound_done=True)
    return notes


# --- the day advance -------------------------------------------------------------------


def _session_complete(db, config, spot_id, rng):
    day = db.session().day + 1
    for car in db.cars_at(v.AT_YARD, v.LOCALS_TRACK):
        if car.assigned_spot is None and car.load == v.EMPTY:
            db.update_car(car.id, days_held=car.days_held + 1)
    bad_order_spots = {c.loc_ref for c in db.cars() if c.loc_kind == v.AT_SPOT and c.bad_order}
    for spot in config.spots:
        state = spots.advance(spot, db.spot_state(spot.spot_id), rng, config.settings, day,
                              frozen=spot.spot_id in bad_order_spots)
        db.put_spot_state(state)
    db.update_session(day=day, **{flag: False for flag in _DONE_NAME}, local_has_work=False)
    plan = plan_day(db, config, rng)
    return [f"Day {day} begins.", *plan.notes]


# --- helpers ---------------------------------------------------------------------------


def _car_at(db: Database, spot_id: str) -> Car | None:
    cars = db.cars_at(v.AT_SPOT, spot_id)
    return cars[0] if cars else None


def _next_seq(db: Database, kind: str, ref: str) -> int:
    seqs = [c.seq or 0 for c in db.cars_at(kind, ref)]
    seqs += [e.seq or 0 for e in db.engines_at(kind, ref)]
    return max(seqs, default=0) + 1


def _to_track(db: Database, car: Car, track: str, **changes) -> None:
    db.update_car(car.id, loc_kind=v.AT_YARD, loc_ref=track,
                  seq=_next_seq(db, v.AT_YARD, track), **changes)


def _to_train(db: Database, car: Car, train: str, **changes) -> None:
    db.update_car(car.id, loc_kind=v.AT_TRAIN, loc_ref=train,
                  seq=_next_seq(db, v.AT_TRAIN, train), **changes)


def _arrive(db: Database, train: str, world: str) -> list[str]:
    """A manifest reaches its world and dissolves into it."""
    notes = []
    for car in db.cars_at(v.AT_TRAIN, train):
        if car.bad_order and world == v.WEST_STAGING:
            db.remove_from_consist_plans(car_id=car.id)
            db.remove_car(car.id)
            notes.append(f"Bad order car {car.label} reached West staging and left the "
                         f"roster — take it off the layout.")
            continue
        db.update_car(car.id, loc_kind=v.AT_WORLD, loc_ref=world, seq=None,
                      load=v.NOT_TRACKED, assigned_spot=None, dest_world=None, days_held=0)
    for engine in db.engines_at(v.AT_TRAIN, train):
        db.update_engine(engine.id, loc_kind=v.AT_WORLD, loc_ref=world, seq=None)
    return notes


_EFFECTS = {
    v.WEST_CHORE_DONE: _west_chore,
    v.EAST_CHORE_DONE: _east_chore,
    v.SWITCH_WESTBOUND_DONE: _switch_westbound,
    v.PULL_DONE: _pull,
    v.SET_OUT_DONE: _set_out,
    v.LOCAL_BACK: _local_back,
    v.LOCAL_RETURN_DONE: _local_return,
    v.SWITCH_EASTBOUND_DONE: _switch_eastbound,
    v.SESSION_COMPLETE: _session_complete,
}
