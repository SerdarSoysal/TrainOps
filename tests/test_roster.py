"""Step 4: roster changes after the cold start (retire, sync)."""

import shutil

import pytest

from trainops import vocab as v
from trainops.coldstart import cold_start
from trainops.config import load_config
from trainops.db import Database
from trainops.roster import retire_car, retire_engine, sync_roster
from trainops.rosterfiles import RosterFileError


@pytest.fixture
def config(samples_dir):
    return load_config(samples_dir / "config.yaml")


@pytest.fixture
def files(tmp_path, samples_dir):
    cars = tmp_path / "cars.csv"
    engines = tmp_path / "engines.csv"
    shutil.copy(samples_dir / "cars.csv", cars)
    shutil.copy(samples_dir / "engines.csv", engines)
    return cars, engines


@pytest.fixture
def db(config, files):
    database = Database.open(":memory:")
    cold_start(database, config, *files)
    yield database
    database.close()


def drop_line(path, text):
    lines = path.read_text().splitlines()
    path.write_text("\n".join(l for l in lines if text not in l) + "\n")


def add_line(path, line):
    path.write_text(path.read_text() + line + "\n")


def put_car_on_spot(db, mark, number, spot_id):
    with db.transaction():
        car = db.find_car(mark, number)
        return db.update_car(car.id, loc_kind=v.AT_SPOT, loc_ref=spot_id)


# --- retiring ----------------------------------------------------------------------------


def test_retiring_a_car_at_a_spot_marks_it_bad_order(db, config):
    car = put_car_on_spot(db, "UTLX", "98120", "northfield_chemical")
    with db.transaction():
        note = retire_car(db, config, car)
    assert note == (
        "Car UTLX 98120 at Northfield Paper, Chemical unloading is marked Bad order: the local "
        "will pull it and it leaves the roster at West staging."
    )
    car = db.find_car("UTLX", "98120")
    assert car.bad_order is True
    assert car.loc_ref == "northfield_chemical"  # still there until the local pulls it


def test_retiring_a_bad_order_car_again_changes_nothing(db, config):
    car = put_car_on_spot(db, "UTLX", "98120", "northfield_chemical")
    with db.transaction():
        retire_car(db, config, car)
        note = retire_car(db, config, db.car(car.id))
    assert note.endswith("is already marked Bad order.")


def test_retiring_a_car_elsewhere_removes_it(db, config):
    car = db.find_car("CSXT", "14587")
    with db.transaction():
        note = retire_car(db, config, car)
    assert note == "Car CSXT 14587 retired — take it off the layout (West staging)."
    assert db.find_car("CSXT", "14587") is None


def test_retiring_a_planned_car_shortens_the_train(db, config):
    a, b, c = (db.find_car("CSXT", n) for n in ("14587", "15102", "259103"))
    engine = db.find_engine("BNSF", "6180")
    with db.transaction():
        db.set_consist_plan(
            v.EASTBOUND_MANIFEST, engine_ids=[engine.id], car_ids=[a.id, b.id, c.id]
        )
        retire_car(db, config, b)
    plan = db.consist_plan(v.EASTBOUND_MANIFEST)
    assert [p.seq for p in plan] == [1, 2, 3]
    assert [p.car_id for p in plan] == [None, a.id, c.id]


def test_retiring_an_engine(db):
    engine = db.find_engine("UP", "8612")
    with db.transaction():
        db.set_consist_plan(v.WESTBOUND_MANIFEST, engine_ids=[engine.id], car_ids=[])
        note = retire_engine(db, engine)
    assert note == "Engine UP 8612 retired — take it off the layout (Storage)."
    assert db.find_engine("UP", "8612") is None
    assert db.consist_plan(v.WESTBOUND_MANIFEST) == []


# --- syncing ------------------------------------------------------------------------------


def test_sync_with_unchanged_files_changes_nothing(db, config, files):
    assert sync_roster(db, config, *files) == [
        "The roster already matches the files; nothing changed."
    ]


def test_sync_adds_new_cars_and_engines(db, config, files):
    cars, engines = files
    add_line(cars, "UP,99001,boxcar,west staging")
    add_line(engines, "UP,4141,SD70M,manifest,Storage")
    assert sync_roster(db, config, cars, engines) == [
        "Car UP 99001 (boxcar) added to West staging.",
        "Engine UP 4141 added to Storage.",
    ]
    car = db.find_car("UP", "99001")
    assert (car.loc_ref, car.origin_world) == (v.WEST_STAGING, v.WEST_STAGING)


def test_new_cars_only_go_into_west_staging(db, config, files):
    cars, engines = files
    add_line(cars, "UP,99001,boxcar,East staging")
    with pytest.raises(RosterFileError) as info:
        sync_roster(db, config, cars, engines)
    assert info.value.problems == [
        "cars.csv, line 67: new car UP 99001 can only be added to West staging "
        "(East staging holds exactly the last Eastbound manifest)"
    ]
    assert db.find_car("UP", "99001") is None


def test_existing_cars_keep_their_place(db, config, files):
    cars, engines = files
    with db.transaction():
        car = db.find_car("CSXT", "14587")
        db.update_car(car.id, loc_kind=v.AT_YARD, loc_ref=v.LOCALS_TRACK, seq=1)
    sync_roster(db, config, cars, engines)  # the file still says West staging
    assert db.find_car("CSXT", "14587").loc_ref == v.LOCALS_TRACK


def test_sync_retires_missing_cars(db, config, files):
    cars, engines = files
    put_car_on_spot(db, "UTLX", "98120", "northfield_chemical")
    drop_line(cars, "UTLX,98120")
    drop_line(cars, "CSXT,14587")
    assert sync_roster(db, config, cars, engines) == [
        "Car UTLX 98120 at Northfield Paper, Chemical unloading is marked Bad order: the local "
        "will pull it and it leaves the roster at West staging.",
        "Car CSXT 14587 retired — take it off the layout (West staging).",
    ]
    # Syncing again doesn't repeat the bad-order note.
    assert sync_roster(db, config, cars, engines) == [
        "The roster already matches the files; nothing changed."
    ]


def test_car_type_can_never_change(db, config, files):
    cars, engines = files
    cars.write_text(cars.read_text().replace("CSXT,14587,boxcar", "CSXT,14587,covered hopper"))
    with pytest.raises(RosterFileError) as info:
        sync_roster(db, config, cars, engines)
    assert info.value.problems == [
        "cars.csv, line 18: CSXT 14587 is a boxcar in the roster but 'covered hopper' in the "
        "file — a car's type can't be changed"
    ]


def test_car_type_capitals_are_not_a_change(db, config, files):
    cars, engines = files
    cars.write_text(cars.read_text().replace("CSXT,14587,boxcar", "CSXT,14587,Boxcar"))
    assert sync_roster(db, config, cars, engines) == [
        "The roster already matches the files; nothing changed."
    ]


def test_sync_updates_engine_pool_and_model(db, config, files):
    cars, engines = files
    engines.write_text(engines.read_text().replace("NS,8100,ES44AC,manifest", "NS,8100,,local"))
    assert sync_roster(db, config, cars, engines) == [
        "Engine NS 8100 moved from the manifest pool to the local pool.",
        "Engine NS 8100 model changed to (none).",
    ]
    engine = db.find_engine("NS", "8100")
    assert (engine.pool, engine.model) == (v.POOL_LOCAL, None)


def test_sync_retires_missing_engines(db, config, files):
    cars, engines = files
    drop_line(engines, "UP,8612")
    assert sync_roster(db, config, cars, engines) == [
        "Engine UP 8612 retired — take it off the layout (Storage)."
    ]


def test_sync_refuses_to_leave_too_few_engines(db, config, files):
    cars, engines = files
    drop_line(engines, ",switcher,")
    with pytest.raises(RosterFileError) as info:
        sync_roster(db, config, cars, engines)
    assert "needs at least 1 switcher engine" in info.value.problems[0]
    assert db.find_engine("CSXT", "1203") is not None


def test_sync_refuses_more_cars_than_west_staging_holds(db, config, files):
    cars, engines = files
    for n in range(22):  # 49 in West staging, room for 21
        add_line(cars, f"UP,{90000 + n},boxcar,West staging")
    with pytest.raises(RosterFileError) as info:
        sync_roster(db, config, cars, engines)
    assert info.value.problems == [
        "cars.csv: 22 new cars won't fit in West staging (room for 21)"
    ]


def test_a_problem_anywhere_means_nothing_changes(db, config, files):
    cars, engines = files
    add_line(cars, "UP,99001,boxcar,West staging")
    drop_line(cars, "CSXT,14587")
    add_line(engines, "UP,4141,SD70M,road,Storage")
    with pytest.raises(RosterFileError):
        sync_roster(db, config, cars, engines)
    assert db.find_car("UP", "99001") is None
    assert db.find_car("CSXT", "14587") is not None
