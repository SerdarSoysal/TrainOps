"""Step 9: work lists and spot display text."""

import random
from dataclasses import replace

import pytest

from trainops import vocab as v
from trainops.config import parse_config
from trainops.db import Car, SpotState
from trainops.worklists import (
    DONE,
    chore_sheet,
    current_work,
    local_list,
    local_return_list,
    spot_lines,
    spot_text,
    switch_list,
)

from test_signals import local_moves, railroad, run_day, send, to_the_local  # noqa: F401


@pytest.fixture
def busy(railroad):  # noqa: F811
    """The sample railroad a few days in, so every kind of move exists."""
    db, config = railroad
    rng = random.Random(11)
    for _ in range(4):
        run_day(db, config, rng)
    return db, config


# --- chore sheets ----------------------------------------------------------------------


def test_chore_sheet_has_three_sections_and_the_train_list(busy):
    db, config = busy
    text = chore_sheet(db, config, v.EAST_STAGING)
    lines = text.splitlines()
    assert lines[0] == "EAST LOOP — Westbound manifest"
    assert lines[1].startswith("1. Engines from storage → staging:  ")
    assert lines[2].startswith("2. Engines from staging → storage:  ")
    assert lines[3] == "3. Train list"
    assert lines[4].startswith("   Engines (lead first):  ")
    assert lines[-1].strip() == f"[ {v.EAST_CHORE_DONE} ]"

    plan = [db.car(e.car_id) for e in db.consist_plan(v.WESTBOUND_MANIFEST) if e.car_id]
    car_lines = lines[6:-1]
    assert len(car_lines) == len(plan)
    for number, (line, car) in enumerate(zip(car_lines, plan), 1):
        assert line.split()[:3] == [str(number), car.mark, car.number]
        if car.assigned_spot:
            industry = config.spot(car.assigned_spot).industry_name
            assert f"{car.load} → {industry}   (Local block)" in line
        else:
            assert "Local block" not in line


def test_chore_sheet_engine_moves(busy):
    db, config = busy
    plan = [db.engine(e.engine_id) for e in db.consist_plan(v.EASTBOUND_MANIFEST) if e.engine_id]
    from_storage = [e.label for e in plan if e.loc_kind == v.AT_STORAGE]
    text = chore_sheet(db, config, v.WEST_STAGING)
    expected = ", ".join(from_storage) or "none"
    assert f"1. Engines from storage → staging:  {expected}" in text


def test_empty_sections_say_none(busy):
    db, config = busy
    with db.transaction():
        for engine in db.engines():
            if engine.loc_kind == v.AT_WORLD and engine.loc_ref == v.WEST_STAGING:
                db.update_engine(engine.id, loc_kind=v.AT_STORAGE, loc_ref=v.STORAGE)
    assert "2. Engines from staging → storage:  none" in chore_sheet(db, config, v.WEST_STAGING)


def test_done_chore_shows_done(busy):
    db, config = busy
    send(db, config, v.WEST_CHORE_DONE)
    assert chore_sheet(db, config, v.WEST_STAGING) == f"WEST STAGING — Eastbound manifest\n  {DONE}"


# --- switching lists -------------------------------------------------------------------


def test_switch_westbound_list(busy):
    db, config = busy
    send(db, config, v.WEST_CHORE_DONE)
    send(db, config, v.EAST_CHORE_DONE)
    block = [c for c in db.cars_at(v.AT_TRAIN, v.WESTBOUND_MANIFEST) if c.assigned_spot]
    track = db.cars_at(v.AT_YARD, v.WESTBOUND_TRACK)
    lines = switch_list(db, config, v.WESTBOUND_MANIFEST).splitlines()
    assert lines[0] == "WESTBOUND MANIFEST — Switch westbound"
    text = "\n".join(lines)
    if block:
        cars = "car" if len(block) == 1 else "cars"
        head = f"  Move {len(block)} {cars} from the main to the Locals track:"
        assert head in lines
        assert lines[lines.index(head) + 1].strip().startswith(f"{block[0].label} {block[0].type}")
    if track:
        cars = "car" if len(track) == 1 else "cars"
        assert f"  Move {len(track)} {cars} from the Westbound track to the main:" in lines
    for car in block + track:
        assert car.label in text
    assert lines[-1].strip() == f"[ {v.SWITCH_WESTBOUND_DONE} ]"
    assert current_work(db, config) == "\n".join(lines)


def test_overload_is_shown_only_when_over_twenty(busy):
    db, config = busy
    send(db, config, v.WEST_CHORE_DONE)
    send(db, config, v.EAST_CHORE_DONE)
    with db.transaction():  # empty the Westbound track: train well under 20 cars
        for car in db.cars_at(v.AT_YARD, v.WESTBOUND_TRACK):
            db.update_car(car.id, loc_kind=v.AT_WORLD, loc_ref=v.WEST_STAGING, seq=None)
    if len(db.cars_at(v.AT_TRAIN, v.WESTBOUND_MANIFEST)) <= 20:
        assert "overload" not in switch_list(db, config, v.WESTBOUND_MANIFEST)
    # Put enough West staging cars on the Westbound track to overload the train.
    spare = db.cars_at(v.AT_WORLD, v.WEST_STAGING)[:15]
    with db.transaction():
        for seq, car in enumerate(spare, 100):
            db.update_car(car.id, loc_kind=v.AT_YARD, loc_ref=v.WESTBOUND_TRACK, seq=seq)
    assert "— exception overload train)" in switch_list(db, config, v.WESTBOUND_MANIFEST)


def test_switch_eastbound_pickup_is_provisional_until_the_local_return_job(busy):
    db, config = busy
    text = switch_list(db, config, v.EASTBOUND_MANIFEST)
    assert "(More cars may reach the Eastbound track during the Local return job.)" in text


# --- the local -------------------------------------------------------------------------


def test_local_list_moves_by_industry(busy):
    db, config = busy
    to_the_local(db, config)
    pulls, setouts = local_moves(db)
    text = local_list(db, config)
    for spot_id in pulls:
        car = db.cars_at(v.AT_SPOT, spot_id)[0]
        assert f"Pull  {car.label} ({car.type}," in text
        assert f"← {config.spot(spot_id).name}" in text
    for spot_id in setouts:
        car = next(c for c in db.cars_at(v.AT_TRAIN, v.LOCAL) if c.assigned_spot == spot_id)
        assert f"Spot  {car.label} ({car.type}, {car.load.lower()})" in text
    for industry in config.industries:
        if any(config.spot(s).industry_id == industry.id for s in pulls + setouts):
            assert industry.name.upper() in text.splitlines()
    swaps = set(pulls) & set(setouts)
    assert text.count("(after pull)") == len(swaps)
    assert text.splitlines()[-1].strip() == f"[ {v.LOCAL_BACK} ]"


def test_pulled_car_shows_only_where_it_goes_next(busy):
    db, config = busy
    to_the_local(db, config)
    pulls, _ = local_moves(db)
    spot_id = pulls[0]
    car = db.cars_at(v.AT_SPOT, spot_id)[0]
    send(db, config, v.PULL_DONE, spot_id)
    text = local_list(db, config)
    assert f"Pull  {car.label}" not in text
    section = text.split("PULLED, BACK TO THE YARD\n")[1]
    line = next(l for l in section.splitlines() if car.label in l)
    assert "→ " in line and "track" in line
    assert config.spot(spot_id).name not in line


def test_spotted_car_is_marked_done(busy):
    db, config = busy
    to_the_local(db, config)
    car = next(c for c in db.cars_at(v.AT_TRAIN, v.LOCAL)
               if not db.cars_at(v.AT_SPOT, c.assigned_spot))
    send(db, config, v.SET_OUT_DONE, car.assigned_spot)
    line = next(l for l in local_list(db, config).splitlines() if car.label in l)
    assert line.endswith(DONE)


# --- the Local return job --------------------------------------------------------------


def test_local_return_list(busy):
    db, config = busy
    to_the_local(db, config)
    assert local_return_list(db, config).endswith("Made when the local is back in the yard.")
    pulls, _ = local_moves(db)
    for spot_id in pulls:
        send(db, config, v.PULL_DONE, spot_id)
    send(db, config, v.LOCAL_BACK)
    text = local_return_list(db, config)
    assert text.startswith("LOCAL RETURN JOB — the local's cars on the main")
    for car in db.cars_at(v.AT_TRAIN, v.LOCAL):
        assert car.label in text
    # Nothing was set out, so the local's cars for spots go back to the Locals track.
    assert "from the main to the Locals track:" in text
    # One list of moves: no numbered steps, no separate sections.
    assert all(l.startswith(("LOCAL RETURN JOB", "  Move ", "      ", " " * 40))
               for l in text.splitlines())
    assert text.splitlines()[-1].strip() == f"[ {v.LOCAL_RETURN_DONE} ]"


def test_local_return_list_includes_cars_leaving_the_locals_track(busy):
    db, config = busy
    to_the_local(db, config)
    with db.transaction():
        car = db.cars_at(v.AT_WORLD, v.WEST_STAGING)[0]
        db.update_car(car.id, loc_kind=v.AT_YARD, loc_ref=v.LOCALS_TRACK, seq=99,
                      load=v.EMPTY, days_held=9)
    send(db, config, v.LOCAL_BACK)
    text = local_return_list(db, config)
    lines = text.splitlines()
    head = next(l for l in lines
                if l.startswith("  Move") and "from the Locals track to the" in l)
    assert car.label in lines[lines.index(head) + 1]


# --- spots -----------------------------------------------------------------------------


@pytest.fixture
def two_spots():
    return parse_config({"industries": [{"id": "mill", "name": "Mill", "spots": [
        {"spot_id": "pit", "name": "Pit", "requirement_mode": "fixed",
         "car_type": "covered hopper", "direction": "incoming", "source": "West",
         "base_processing_days": 2},
        {"spot_id": "door", "name": "Door", "requirement_mode": "fixed",
         "car_type": "boxcar", "direction": "outgoing", "pattern": ["East"],
         "base_processing_days": 2},
    ]}]})


def car(**fields):
    base = dict(id=1, mark="CSXT", number="14420", type="covered hopper", loc_kind=v.AT_YARD,
                loc_ref=v.LOCALS_TRACK, seq=1, load=v.LOADED, last_loaded_industry=None,
                origin_world=v.WEST_STAGING, assigned_spot="pit", dest_world=None,
                days_held=0, bad_order=False)
    base.update(fields)
    return Car(**base)


def st(spot_id, state, **fields):
    return replace(SpotState(spot_id=spot_id, state=state, industry_id="mill", identity="x"),
                   **fields)


def test_spot_text_for_every_state(two_spots):
    pit, door = two_spots.spot("pit"), two_spots.spot("door")
    assert spot_text(pit, st("pit", v.AWAITING_CAR), None, None) == \
        "Awaiting car — needs a loaded covered hopper from the West"
    assert spot_text(pit, st("pit", v.AWAITING_CAR), None, car()) == \
        "Awaiting car — needs a loaded covered hopper from the West — " \
        "CSXT 14420 waiting on the Locals track"
    assert spot_text(door, st("door", v.AWAITING_CAR), None, None) == \
        "Awaiting car — needs an empty boxcar to load for the East"
    assert spot_text(pit, st("pit", v.PROCESSING, days_left=1), car(loc_kind=v.AT_SPOT), None) \
        == "Processing CSXT 14420 (covered hopper) — 1 day left"
    assert spot_text(pit, st("pit", v.PROCESSING, days_left=2),
                     car(bad_order=True), None).endswith("— bad order, waiting for the local")
    assert spot_text(door, st("door", v.READY_FOR_PICKUP, out_dest=v.EAST),
                     car(type="boxcar"), None) == \
        "Ready for pickup: CSXT 14420 (boxcar), loaded for the East"
    assert spot_text(pit, st("pit", v.READY_FOR_PICKUP), car(), None) == \
        "Ready for pickup: CSXT 14420 (covered hopper), empty"
    assert spot_text(pit, st("pit", v.IDLE, days_left=2), None, None) == \
        "Idle — 2 days before it wants a car again"


def test_spot_text_says_where_the_coming_car_is(two_spots):
    pit = two_spots.spot("pit")
    awaiting = st("pit", v.AWAITING_CAR)
    on_local = car(loc_kind=v.AT_TRAIN, loc_ref=v.LOCAL)
    on_manifest = car(loc_kind=v.AT_TRAIN, loc_ref=v.EASTBOUND_MANIFEST)
    in_world = car(loc_kind=v.AT_WORLD, loc_ref=v.WEST_STAGING)
    assert spot_text(pit, awaiting, None, on_local).endswith("CSXT 14420 on the local")
    assert spot_text(pit, awaiting, None, on_manifest).endswith(
        "CSXT 14420 coming on the eastbound manifest")
    assert spot_text(pit, awaiting, None, in_world).endswith("CSXT 14420 coming from West staging")


def test_spot_lines_cover_every_spot_by_name(busy):
    db, config = busy
    lines = spot_lines(db, config)
    assert [l.split(":")[0] for l in lines] == [s.label for s in config.spots]


# --- the current job -------------------------------------------------------------------


def test_current_work_follows_the_session(busy):
    db, config = busy
    assert current_work(db, config).startswith("WEST STAGING — Eastbound manifest")
    send(db, config, v.WEST_CHORE_DONE)
    assert f"WEST STAGING — Eastbound manifest\n  {DONE}" in current_work(db, config)
    send(db, config, v.EAST_CHORE_DONE)
    assert current_work(db, config).startswith("WESTBOUND MANIFEST — Switch westbound")
    send(db, config, v.SWITCH_WESTBOUND_DONE)
    assert current_work(db, config).startswith("LOCAL — day ")
    send(db, config, v.LOCAL_BACK)
    if not db.session().local_return_done:
        assert current_work(db, config).startswith("LOCAL RETURN JOB")
        send(db, config, v.LOCAL_RETURN_DONE)
    assert current_work(db, config).startswith("EASTBOUND MANIFEST — Switch eastbound")
    send(db, config, v.SWITCH_EASTBOUND_DONE)
    assert current_work(db, config).splitlines()[-1].strip() == f"[ {v.SESSION_COMPLETE} ]"
