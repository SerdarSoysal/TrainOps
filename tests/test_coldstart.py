"""Step 4: cold start."""

import shutil
import sqlite3

import pytest

from trainops import vocab as v
from trainops.coldstart import cold_start
from trainops.config import load_config
from trainops.db import SCHEMA_VERSION, Database, DatabaseError, SpotState
from trainops.reconcile import check_config
from trainops.rosterfiles import RosterFileError


@pytest.fixture
def db():
    database = Database.open(":memory:")
    yield database
    database.close()


@pytest.fixture
def config(samples_dir):
    return load_config(samples_dir / "config.yaml")


@pytest.fixture
def files(tmp_path, samples_dir):
    """Copies of the sample roster files that a test may change."""
    cars = tmp_path / "cars.csv"
    engines = tmp_path / "engines.csv"
    shutil.copy(samples_dir / "cars.csv", cars)
    shutil.copy(samples_dir / "engines.csv", engines)
    return cars, engines


def test_sample_roster_cold_starts(db, config, files):
    notes = cold_start(db, config, *files)
    assert notes == [
        "Cold start done: 65 cars (16 in East staging, 49 in West staging), 19 engines, "
        "7 spots awaiting cars. Day 1 begins."
    ]
    assert len(db.cars()) == 65
    assert len(db.engines()) == 19

    car = db.find_car("CSXT", "14420")
    assert (car.loc_kind, car.loc_ref, car.seq) == (v.AT_WORLD, v.EAST_STAGING, None)
    assert car.origin_world == v.EAST_STAGING
    assert car.load == v.NOT_TRACKED
    assert car.bad_order is False

    engine = db.find_engine("BNSF", "7710")
    assert (engine.loc_kind, engine.loc_ref, engine.pool) == (
        v.AT_WORLD,
        v.EAST_STAGING,
        v.POOL_MANIFEST,
    )
    assert db.find_engine("CSXT", "1203").loc_kind == v.AT_STORAGE

    assert {s.state for s in db.spot_states().values()} == {v.AWAITING_CAR}
    assert db.session().day == 1
    assert check_config(db, config) == []  # the program can now start


def test_cold_start_wipes_what_was_there(db, config, files):
    cold_start(db, config, *files)
    with db.transaction():
        db.update_session(day=40, job_a_done=True)
        car = db.find_car("CSXT", "14420")
        db.update_car(car.id, loc_kind=v.AT_YARD, loc_ref=v.LOCALS_TRACK, seq=1)
        db.set_consist_plan(v.LOCAL, engine_ids=[], car_ids=[car.id])
        state = db.spot_state("harbor_pit")
        db.put_spot_state(
            SpotState(
                "harbor_pit",
                v.PROCESSING,
                days_left=1,
                industry_id=state.industry_id,
                identity=state.identity,
            )
        )

    cold_start(db, config, *files)
    session = db.session()
    assert session.day == 1 and session.job_a_done is False
    assert db.find_car("CSXT", "14420").loc_ref == v.EAST_STAGING
    assert db.consist_plan(v.LOCAL) == []
    assert db.spot_state("harbor_pit").state == v.AWAITING_CAR


def test_bad_files_change_nothing_and_report_everything(db, config, files):
    cold_start(db, config, *files)
    cars, engines = files
    cars.write_text(
        cars.read_text() + "CSXT,14420,boxcar,West staging\nUP,1,boxcar,Chicago\n"
    )
    engines.write_text(engines.read_text().replace("switcher", "yard"))

    with pytest.raises(RosterFileError) as info:
        cold_start(db, config, cars, engines)
    assert info.value.problems == [
        "cars.csv, line 67: CSXT 14420 is already on line 2",
        "cars.csv, line 68: location is 'Chicago' — expected East staging or West staging",
        "engines.csv, line 20: pool is 'yard' — expected Local, Switcher or Manifest",
    ]
    assert len(db.cars()) == 65  # the earlier cold start is untouched


def test_too_many_cars_for_staging(db, config, files):
    cars, engines = files
    extra = "".join(f"UP,{n},boxcar,East staging\n" for n in range(1, 16))  # 16 + 15 = 31
    cars.write_text(cars.read_text() + extra)
    with pytest.raises(RosterFileError) as info:
        cold_start(db, config, cars, engines)
    assert info.value.problems == ["cars.csv: 31 cars are in East staging, but it holds 30"]


def test_too_few_engines(db, config, files):
    cars, engines = files
    lines = engines.read_text().splitlines()
    engines.write_text("\n".join(l for l in lines if ",switcher," not in l) + "\n")
    with pytest.raises(RosterFileError) as info:
        cold_start(db, config, cars, engines)
    assert info.value.problems == [
        "engines.csv: needs at least 1 switcher engine (the yard switcher); found 0"
    ]


def test_warns_about_spots_no_car_can_serve(db, config, files):
    cars, engines = files
    lines = cars.read_text().splitlines()
    cars.write_text("\n".join(l for l in lines if ",flatcar," not in l) + "\n")
    notes = cold_start(db, config, cars, engines)
    assert notes[1:] == [
        "Warning: no car in the roster can serve Transfer Facility, Team track 1 (flatcar)."
    ]


def test_car_types_match_spots_regardless_of_capitals(db, config, files):
    cars, engines = files
    cars.write_text(cars.read_text().replace(",flatcar,", ",Flatcar,"))
    notes = cold_start(db, config, cars, engines)
    assert len(notes) == 1  # no warning


def test_cold_start_replaces_a_database_from_another_version(tmp_path, config, files):
    path = tmp_path / "state.sqlite"
    Database.open(path).close()
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()

    with pytest.raises(DatabaseError):
        Database.open(path)
    with Database.open(path, discard_other_version=True) as db:
        cold_start(db, config, *files)
        assert len(db.cars()) == 65
