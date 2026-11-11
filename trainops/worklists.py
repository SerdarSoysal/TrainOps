"""Work lists and spot display text (spec Section 12), as plain text.

Everything is worked out from the records when asked for, so a list always
matches what the signals have done so far:

- chore_sheet(world): the pre-session chore sheet for one world
- switch_list(train): Switch westbound or Switch eastbound
- local_list(): the local's moves by industry
- local_return_list(): sorting the local's cars (once the local is back)
- spot_lines(): one plain-language line per spot (web page now, LCDs later)
- current_work(): the list for the job the session is waiting on

The order of cars inside a Local block or on the local is never given, and a
yard job is one list of moves grouped by from -> to ("Move 3 cars from the
main to the Locals track: ..."); the crew does them in whatever order suits
them (user, 2026-11-11). A car pulled from an
industry is shown only by where it goes next (user, 2026-11-11).
"""

from __future__ import annotations

from trainops import spots
from trainops import vocab as v
from trainops.config import Config, Spot
from trainops.db import Car, Database, Engine
from trainops.signals import current_job
from trainops.yardwork import local_return, switch_eastbound, switch_westbound, train_cars

NONE = "none"
MAIN = "main"  # where a manifest, or the local back from its run, stands for yard work
DONE = "✓ done"

_WORLD_OF_TRAIN = {
    v.EASTBOUND_MANIFEST: v.WEST_STAGING,  # made up in West staging
    v.WESTBOUND_MANIFEST: v.EAST_STAGING,  # made up in the East loop
}
_CHORE_TITLE = {
    v.WEST_STAGING: ("WEST STAGING — Eastbound manifest", v.WEST_CHORE_DONE, "west_chore_done"),
    v.EAST_STAGING: ("EAST LOOP — Westbound manifest", v.EAST_CHORE_DONE, "east_chore_done"),
}


def button(text: str) -> str:
    return f"{'':>40}[ {text} ]"


# --- chore sheets ----------------------------------------------------------------------


def chore_sheet(db: Database, config: Config, world: str) -> str:
    """One world's pre-session chore sheet (Section 12.1)."""
    title, signal, flag = _CHORE_TITLE[world]
    train = v.EASTBOUND_MANIFEST if world == v.WEST_STAGING else v.WESTBOUND_MANIFEST
    if getattr(db.session(), flag):
        return f"{title}\n  {DONE}"

    plan = db.consist_plan(train)
    engines = [db.engine(e.engine_id) for e in plan if e.engine_id is not None]
    cars = [db.car(e.car_id) for e in plan if e.car_id is not None]
    planned_ids = {e.id for e in engines}
    to_staging = [e for e in engines if e.loc_kind == v.AT_STORAGE]
    to_storage = [e for e in db.engines_at(v.AT_WORLD, world) if e.id not in planned_ids]

    lines = [
        title,
        f"1. Engines from storage → staging:  {_engine_names(to_staging)}",
        f"2. Engines from staging → storage:  {_engine_names(to_storage)}",
        "3. Train list",
        f"   Engines (lead first):  {_engine_names(engines)}",
        "   Cars (head → rear):" + ("" if cars else f"  {NONE}"),
    ]
    width = max((len(c.label) for c in cars), default=0)
    type_width = max((len(c.type) for c in cars), default=0)
    for number, car in enumerate(cars, 1):
        line = f"    {number:>2}  {car.label:<{width}}  {car.type:<{type_width}}"
        if car.assigned_spot:
            spot = config.spots_by_id.get(car.assigned_spot)
            where = spot.industry_name if spot else car.assigned_spot
            line += f"  {car.load} → {where}   (Local block)"
        lines.append(line.rstrip())
    lines.append(button(signal))
    return "\n".join(lines)


def _engine_names(engines: list[Engine]) -> str:
    return ", ".join(e.label for e in engines) or NONE


# --- Switch westbound and Switch eastbound ----------------------------------------------


def switch_list(db: Database, config: Config, train: str) -> str:
    """Switch westbound (Westbound manifest) or Switch eastbound (Eastbound manifest)."""
    session = db.session()
    if train == v.WESTBOUND_MANIFEST:
        name, signal, track = v.SWITCH_WESTBOUND, v.SWITCH_WESTBOUND_DONE, v.WESTBOUND_TRACK
        done, final = session.switch_westbound_done, True
        job = switch_westbound(db, config)
    else:
        name, signal, track = v.SWITCH_EASTBOUND, v.SWITCH_EASTBOUND_DONE, v.EASTBOUND_TRACK
        done, final = session.switch_eastbound_done, session.local_return_done
        job = switch_eastbound(db, config)
    title = f"{train.upper()} — {name}"
    if done:
        return f"{title}\n  {DONE}"

    lines = [title] + _moves([
        (MAIN, v.LOCALS_TRACK, job.cut),
        (track, MAIN, job.pickup),
    ])
    if not final:
        lines.append(f"  (More cars may reach the {track} during the Local return job.)")
    if job.left_behind:
        full = "West staging" if train == v.WESTBOUND_MANIFEST else "The East loop"
        lines.append(f"   ({len(job.left_behind)} {_cars(len(job.left_behind))} stay on "
                     f"{track}: {full} is full)")
    if final and job.overload:
        lines.append(f"  (Train leaves with {job.length_after} cars — exception overload train)")
    lines.append(button(signal))
    return "\n".join(lines)


def _cars(count: int) -> str:
    return "car" if count == 1 else "cars"


def _moves(groups) -> list[str]:
    """A yard job's moves, one group per (from, to); the crew picks the order."""
    lines = []
    for source, dest, cars in groups:
        if not cars:
            continue
        lines.append(f"  Move {len(cars)} {_cars(len(cars))} from the {source} to the {dest}:")
        names = [f"{c.label} {c.type}" + (" (bad order)" if c.bad_order else "") for c in cars]
        lines += _wrap(names, indent=6, width=76)
    return lines or ["  Nothing to move."]


def _wrap(items: list[str], indent: int, width: int) -> list[str]:
    """Comma-separated items over several lines, never splitting an item."""
    lines, line = [], ""
    for i, item in enumerate(items):
        piece = item + ("," if i < len(items) - 1 else "")
        if line and indent + len(line) + 1 + len(piece) > width:
            lines.append(" " * indent + line)
            line = piece
        else:
            line = f"{line} {piece}" if line else piece
    return lines + [" " * indent + line]


# --- the local -------------------------------------------------------------------------


def local_list(db: Database, config: Config) -> str:
    """The local's moves, by industry (Section 12.3)."""
    session = db.session()
    title = f"LOCAL — day {session.day}"
    if session.local_back:
        return f"{title}\n  {DONE}" if session.local_has_work else \
            f"{title}\n  No work for the local today."

    states = db.spot_states()
    at_spot = {c.loc_ref: c for c in db.cars() if c.loc_kind == v.AT_SPOT}
    pulls: dict[str, Car] = {
        spot_id: car for spot_id, car in at_spot.items()
        if car.bad_order or states[spot_id].state == v.READY_FOR_PICKUP
    }
    pending: dict[str, Car] = {}
    spotted: dict[str, Car] = {}
    for entry in db.consist_plan(v.LOCAL):
        if entry.car_id is None:
            continue
        car = db.car(entry.car_id)
        if car.assigned_spot is not None:
            pending[car.assigned_spot] = car
        elif car.loc_kind == v.AT_SPOT:
            spotted[car.loc_ref] = car

    lines = [title]
    for industry in config.industries:
        rows = []
        for spot in industry.spots:
            sid = spot.spot_id
            if sid in pulls:
                car = pulls[sid]
                rows.append((f"Pull  {car.label} ({car.type}, {_pull_load(spot, states[sid], car)})",
                             f"← {spot.name}", f"[ {v.PULL_DONE} ]"))
            if sid in pending:
                car = pending[sid]
                after = "  (after pull)" if sid in pulls else ""
                rows.append((f"Spot  {car.label} ({car.type}, {car.load.lower()})",
                             f"→ {spot.name}", f"[ {v.SET_OUT_DONE} ]{after}"))
            elif sid in spotted:
                car = spotted[sid]
                rows.append((f"Spot  {car.label} ({car.type}, {car.load.lower()})",
                             f"→ {spot.name}", DONE))
        if rows:
            lines.append(industry.name.upper())
            lines += _columns(rows, indent=2)
    if len(lines) == 1:
        lines.append("  No work for the local today.")

    pulled = [m for m in local_return(db, config)
              if m.car.loc_kind == v.AT_TRAIN and m.car.assigned_spot is None]
    if pulled:
        lines.append("PULLED, BACK TO THE YARD")
        lines += _columns([(f"{m.car.label} {m.car.type}", f"→ {m.track}", f"({m.reason})")
                           for m in pulled], indent=2)
    lines.append(button(v.LOCAL_BACK))
    return "\n".join(lines)


def _pull_load(spot: Spot, state, car: Car) -> str:
    if car.bad_order:
        return "bad order"
    return "loaded" if spots.need(spot, state).direction == v.OUTGOING else "empty"


# --- the Local return job --------------------------------------------------------------


def local_return_list(db: Database, config: Config) -> str:
    """Sorting the local's cars (Section 12.4); made when the local is back."""
    session = db.session()
    title = "LOCAL RETURN JOB — the local's cars on the main"
    if session.local_return_done:
        return f"{title}\n  {DONE}"
    if not session.local_back:
        return f"{title}\n  Made when the local is back in the yard."
    groups: dict[tuple[str, str], list[Car]] = {}
    for move in local_return(db, config):
        source = MAIN if move.car.loc_kind == v.AT_TRAIN else move.car.loc_ref
        groups.setdefault((source, move.track), []).append(move.car)
    lines = [title] + _moves([(s, d, cars) for (s, d), cars in groups.items()])
    lines.append(button(v.LOCAL_RETURN_DONE))
    return "\n".join(lines)



# --- spots -----------------------------------------------------------------------------


def spot_lines(db: Database, config: Config) -> list[str]:
    """One plain-language line per spot, in configuration order."""
    states = db.spot_states()
    cars = db.cars()
    at_spot = {c.loc_ref: c for c in cars if c.loc_kind == v.AT_SPOT}
    coming: dict[str, Car] = {}
    for car in cars:
        if car.assigned_spot and car.loc_kind != v.AT_SPOT:
            coming.setdefault(car.assigned_spot, car)
    return [
        f"{spot.label}: {spot_text(spot, states[spot.spot_id], at_spot.get(spot.spot_id), coming.get(spot.spot_id))}"
        for spot in config.spots
    ]


def spot_text(spot: Spot, state, car: Car | None, coming: Car | None) -> str:
    """What one spot shows: its state, what it needs, and the car involved."""
    if state.state == v.AWAITING_CAR:
        wanted = spots.need(spot, state)
        text = "Awaiting car — " + (_need_words(wanted) if wanted else "next need not drawn yet")
        if coming:
            text += f" — {coming.label} {_where(coming)}"
        return text
    if state.state == v.PROCESSING:
        text = f"Processing {_car_words(car)}"
        if car and car.bad_order:
            return text + " — bad order, waiting for the local"
        days = state.days_left
        return text + f" — {days} {'day' if days == 1 else 'days'} left"
    if state.state == v.READY_FOR_PICKUP:
        text = f"Ready for pickup: {_car_words(car)}"
        if car and car.bad_order:
            return text + ", bad order"
        if state.out_dest:
            return text + f", loaded for the {state.out_dest}"
        return text + ", empty"
    days = state.days_left
    return f"Idle — {days} {'day' if days == 1 else 'days'} before it wants a car again"


def _need_words(wanted) -> str:
    if wanted.direction == v.INCOMING:
        return f"needs a loaded {wanted.car_type} from the {wanted.side}"
    return f"needs an empty {wanted.car_type} to load for the {wanted.side}"


def _car_words(car: Car | None) -> str:
    return f"{car.label} ({car.type})" if car else "(no car recorded)"


def _where(car: Car) -> str:
    if car.loc_kind == v.AT_YARD:
        return f"waiting on the {car.loc_ref}"
    if car.loc_kind == v.AT_TRAIN:
        return f"on the {car.loc_ref.lower()}" if car.loc_ref == v.LOCAL else \
            f"coming on the {car.loc_ref.lower()}"
    return f"coming from {car.loc_ref}"


# --- the current job -------------------------------------------------------------------


def current_work(db: Database, config: Config) -> str:
    """The list for the job the session is waiting on."""
    job = current_job(db.session())
    if job == v.JOB_CHORES:
        return "\n\n".join(chore_sheet(db, config, w) for w in (v.WEST_STAGING, v.EAST_STAGING))
    if job == v.SWITCH_WESTBOUND:
        return switch_list(db, config, v.WESTBOUND_MANIFEST)
    if job == v.JOB_LOCAL:
        return local_list(db, config)
    if job == v.LOCAL_RETURN:
        return local_return_list(db, config)
    if job == v.SWITCH_EASTBOUND:
        return switch_list(db, config, v.EASTBOUND_MANIFEST)
    return f"Day {db.session().day}: every job is done.\n{button(v.SESSION_COMPLETE)}"


# --- helpers ---------------------------------------------------------------------------


def _columns(rows: list[tuple[str, ...]], indent: int) -> list[str]:
    """Rows of text cells, padded so the columns line up."""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    pad = " " * indent
    return [
        (pad + "  ".join(cell.ljust(w) for cell, w in zip(row, widths))).rstrip()
        for row in rows
    ]
