"""Step 3: the state database."""

import sqlite3

import pytest

from trainops import vocab as v
from trainops.db import SCHEMA_VERSION, Database, DatabaseError, SpotState


@pytest.fixture
def db():
    database = Database.open(":memory:")
    yield database
    database.close()


def add_boxcar(db, number="14420", **overrides):
    values = dict(
        mark="CSXT",
        number=number,
        type="boxcar",
        loc_kind=v.AT_WORLD,
        loc_ref=v.WEST_STAGING,
        origin_world=v.WEST_STAGING,
    )
    values.update(overrides)
    return db.add_car(**values)


# --- creating and opening ------------------------------------------------------


def test_new_database_starts_on_day_one_with_nothing_done(db):
    session = db.session()
    assert session.day == 1
    assert not any(
        [
            session.west_chore_done,
            session.east_chore_done,
            session.job_a_done,
            session.local_back,
            session.job_b_done,
            session.job_c_done,
            session.local_has_work,
        ]
    )
    assert db.cars() == [] and db.engines() == [] and db.spot_states() == {}


def test_saved_data_survives_reopening(tmp_path):
    path = tmp_path / "state.sqlite"
    with Database.open(path) as db:
        with db.transaction():
            add_boxcar(db)
            db.update_session(day=5, job_a_done=True)
    with Database.open(path) as db:
        assert db.find_car("CSXT", "14420").type == "boxcar"
        assert db.session().day == 5
        assert db.session().job_a_done is True


def test_database_from_another_version_is_refused(tmp_path):
    path = tmp_path / "state.sqlite"
    Database.open(path).close()
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(DatabaseError, match="different version of TrainOps"):
        Database.open(path)


# --- transactions -------------------------------------------------------------------


def test_changes_outside_a_transaction_are_refused(db):
    with pytest.raises(RuntimeError, match="inside db.transaction"):
        add_boxcar(db)


def test_transactions_cannot_be_nested(db):
    with db.transaction():
        with pytest.raises(RuntimeError, match="can't be nested"):
            with db.transaction():
                pass


def test_an_error_undoes_the_whole_transaction(db):
    with pytest.raises(ZeroDivisionError):
        with db.transaction():
            add_boxcar(db, "1")
            db.update_session(job_a_done=True)
            1 / 0
    assert db.cars() == []
    assert db.session().job_a_done is False


def test_transaction_can_be_used_again_after_an_error(db):
    with pytest.raises(ZeroDivisionError):
        with db.transaction():
            1 / 0
    with db.transaction():
        add_boxcar(db)
    assert len(db.cars()) == 1


# --- session ---------------------------------------------------------------------------


def test_update_session(db):
    with db.transaction():
        session = db.update_session(day=3, west_chore_done=True)
    assert session.day == 3 and session.west_chore_done is True


def test_update_session_refuses_unknown_fields(db):
    with db.transaction(), pytest.raises(ValueError, match="job_d_done"):
        db.update_session(job_d_done=True)


# --- cars -------------------------------------------------------------------------------


def test_add_and_find_car(db):
    with db.transaction():
        car = add_boxcar(db)
    assert car.label == "CSXT 14420"
    assert car.load == v.NOT_TRACKED
    assert car.days_held == 0
    assert db.find_car("csxt", " 14420 ") == car
    assert db.find_car("CSXT", "99999") is None


def test_duplicate_car_is_refused_regardless_of_capitals(db):
    with db.transaction():
        add_boxcar(db)
    with db.transaction(), pytest.raises(DatabaseError, match="car csxt 14420 is already"):
        add_boxcar(db, mark="csxt")


def test_update_car(db):
    with db.transaction():
        car = add_boxcar(db)
        moved = db.update_car(
            car.id, loc_kind=v.AT_YARD, loc_ref=v.LOCALS_TRACK, seq=1, load=v.EMPTY
        )
    assert (moved.loc_kind, moved.loc_ref, moved.seq, moved.load) == (
        v.AT_YARD,
        v.LOCALS_TRACK,
        1,
        v.EMPTY,
    )


def test_update_car_refuses_unknown_fields(db):
    with db.transaction():
        car = add_boxcar(db)
        with pytest.raises(ValueError, match="colour"):
            db.update_car(car.id, colour="red")


def test_remove_car(db):
    with db.transaction():
        car = add_boxcar(db)
        db.remove_car(car.id)
    assert db.cars() == []
    with db.transaction(), pytest.raises(DatabaseError, match="no car with id"):
        db.remove_car(car.id)


def test_cars_at_a_place_come_in_order(db):
    with db.transaction():
        for number, seq in (("3", 3), ("1", 1), ("2", 2)):
            add_boxcar(db, number, loc_kind=v.AT_YARD, loc_ref=v.EASTBOUND_TRACK, seq=seq)
        add_boxcar(db, "9")
    assert [c.number for c in db.cars_at(v.AT_YARD, v.EASTBOUND_TRACK)] == ["1", "2", "3"]
    assert [c.number for c in db.cars_at(v.AT_WORLD, v.WEST_STAGING)] == ["9"]


@pytest.mark.parametrize(
    "where",
    [
        dict(loc_kind=v.AT_WORLD, loc_ref="Chicago"),  # not a world
        dict(loc_kind=v.AT_YARD, loc_ref=v.LOCALS_TRACK),  # yard needs an order number
        dict(loc_kind=v.AT_WORLD, loc_ref=v.EAST_STAGING, seq=1),  # world has no order
        dict(loc_kind=v.AT_STORAGE, loc_ref=v.STORAGE),  # storage is for engines
        dict(loc_kind=v.AT_TRAIN, loc_ref="Through freight", seq=1),  # not a train
        dict(load="half full"),
        dict(origin_world="E"),  # plain words only
        dict(dest_world="West"),  # a world, not a side
    ],
)
def test_impossible_car_values_are_refused(db, where):
    with db.transaction(), pytest.raises(sqlite3.IntegrityError):
        add_boxcar(db, **where)


def test_a_spot_holds_one_car(db):
    with db.transaction():
        add_boxcar(db, "1", loc_kind=v.AT_SPOT, loc_ref="northfield_door_1")
        with pytest.raises(sqlite3.IntegrityError):
            add_boxcar(db, "2", loc_kind=v.AT_SPOT, loc_ref="northfield_door_1")
        add_boxcar(db, "3", loc_kind=v.AT_SPOT, loc_ref="northfield_door_2")


# --- engines ---------------------------------------------------------------------------


def test_add_find_update_and_remove_engine(db):
    with db.transaction():
        engine = db.add_engine(
            mark="BNSF",
            number="7710",
            model="ES44AC",
            pool=v.POOL_MANIFEST,
            loc_kind=v.AT_STORAGE,
            loc_ref=v.STORAGE,
        )
    assert engine.label == "BNSF 7710"
    assert db.find_engine("bnsf", "7710") == engine
    with db.transaction():
        moved = db.update_engine(
            engine.id, loc_kind=v.AT_TRAIN, loc_ref=v.EASTBOUND_MANIFEST, seq=1
        )
    assert db.engines_at(v.AT_TRAIN, v.EASTBOUND_MANIFEST) == [moved]
    with db.transaction():
        db.remove_engine(engine.id)
    assert db.engines() == []


def test_engine_model_is_optional(db):
    with db.transaction():
        engine = db.add_engine(
            mark="BNSF", number="2310", pool=v.POOL_LOCAL, loc_kind=v.AT_STORAGE, loc_ref=v.STORAGE
        )
    assert engine.model is None


def test_duplicate_engine_is_refused(db):
    kwargs = dict(
        mark="BNSF", number="7710", pool=v.POOL_MANIFEST, loc_kind=v.AT_STORAGE, loc_ref=v.STORAGE
    )
    with db.transaction():
        db.add_engine(**kwargs)
        with pytest.raises(DatabaseError, match="engine BNSF 7710 is already"):
            db.add_engine(**kwargs)


@pytest.mark.parametrize(
    "where",
    [
        dict(loc_kind=v.AT_YARD, loc_ref=v.LOCALS_TRACK, seq=1),  # engines aren't kept in the yard
        dict(loc_kind=v.AT_SPOT, loc_ref="northfield_door_1"),
        dict(loc_kind=v.AT_STORAGE, loc_ref="Engine house"),
        dict(pool="road"),
    ],
)
def test_impossible_engine_values_are_refused(db, where):
    values = dict(
        mark="BNSF", number="7710", pool=v.POOL_MANIFEST, loc_kind=v.AT_STORAGE, loc_ref=v.STORAGE
    )
    values.update(where)
    with db.transaction(), pytest.raises(sqlite3.IntegrityError):
        db.add_engine(**values)


# --- spot states -----------------------------------------------------------------------

PIT = dict(industry_id="harbor_feed", identity="Fixed: covered hopper, Incoming")


def test_spot_state_round_trip(db):
    state = SpotState(
        spot_id="transfer_track_2",
        state=v.PROCESSING,
        days_left=2,
        position=0,
        requirement_number=1,
        requirement_side=v.EAST,
        out_dest=None,
        waiting_since_day=4,
        next_delay=True,
        next_requirement_number=2,
        next_requirement_side=v.WEST,
        industry_id="transfer",
        identity="Random: boxcar, Incoming; covered hopper, Outgoing",
    )
    with db.transaction():
        db.put_spot_state(state)
    assert db.spot_state("transfer_track_2") == state
    assert db.spot_states() == {"transfer_track_2": state}


def test_put_spot_state_replaces_the_old_one(db):
    with db.transaction():
        db.put_spot_state(SpotState.fresh("harbor_pit", day=1, **PIT))
        db.put_spot_state(SpotState("harbor_pit", v.PROCESSING, days_left=1, **PIT))
    assert db.spot_state("harbor_pit").state == v.PROCESSING
    assert len(db.spot_states()) == 1


def test_fresh_spot_state_is_awaiting_a_car():
    state = SpotState.fresh("harbor_pit", day=7, **PIT)
    assert state.state == v.AWAITING_CAR == "Awaiting car"
    assert state.waiting_since_day == 7
    assert state.position == 0


def test_unknown_spot_state_is_none(db):
    assert db.spot_state("nowhere") is None


def test_impossible_spot_values_are_refused(db):
    with db.transaction():
        with pytest.raises(sqlite3.IntegrityError):
            db.put_spot_state(SpotState("harbor_pit", "EMPTY_AWAITING_CAR", **PIT))
        with pytest.raises(sqlite3.IntegrityError):
            db.put_spot_state(SpotState("harbor_pit", "awaiting car", **PIT))  # sentence case only
        with pytest.raises(sqlite3.IntegrityError):
            db.put_spot_state(SpotState("harbor_pit", v.READY_FOR_PICKUP, out_dest="E", **PIT))


# --- consist plan ----------------------------------------------------------------------


def test_consist_plan_puts_engines_first(db):
    with db.transaction():
        engine = db.add_engine(
            mark="BNSF", number="7710", pool=v.POOL_MANIFEST, loc_kind=v.AT_STORAGE, loc_ref=v.STORAGE
        )
        cars = [add_boxcar(db, str(n)) for n in range(3)]
        plan = db.set_consist_plan(
            v.EASTBOUND_MANIFEST, engine_ids=[engine.id], car_ids=[c.id for c in cars]
        )
    assert [p.seq for p in plan] == [1, 2, 3, 4]
    assert plan[0].engine_id == engine.id and plan[0].car_id is None
    assert [p.car_id for p in plan[1:]] == [c.id for c in cars]
    assert db.consist_plan(v.EASTBOUND_MANIFEST) == plan
    assert db.consist_plan(v.WESTBOUND_MANIFEST) == []


def test_setting_a_plan_replaces_that_trains_plan_only(db):
    with db.transaction():
        a, b = add_boxcar(db, "1"), add_boxcar(db, "2")
        db.set_consist_plan(v.EASTBOUND_MANIFEST, engine_ids=[], car_ids=[a.id])
        db.set_consist_plan(v.WESTBOUND_MANIFEST, engine_ids=[], car_ids=[b.id])
        db.set_consist_plan(v.EASTBOUND_MANIFEST, engine_ids=[], car_ids=[b.id])
    assert [p.car_id for p in db.consist_plan(v.EASTBOUND_MANIFEST)] == [b.id]
    assert [p.car_id for p in db.consist_plan(v.WESTBOUND_MANIFEST)] == [b.id]


def test_clear_consist_plans(db):
    with db.transaction():
        car = add_boxcar(db)
        db.set_consist_plan(v.LOCAL, engine_ids=[], car_ids=[car.id])
        db.clear_consist_plans()
    assert db.consist_plan(v.LOCAL) == []


def test_plan_must_name_a_real_car(db):
    with db.transaction(), pytest.raises(sqlite3.IntegrityError):
        db.set_consist_plan(v.LOCAL, engine_ids=[], car_ids=[999])


def test_planned_car_cannot_be_removed_until_plan_is_cleared(db):
    with db.transaction():
        car = add_boxcar(db)
        db.set_consist_plan(v.LOCAL, engine_ids=[], car_ids=[car.id])
    with db.transaction(), pytest.raises(sqlite3.IntegrityError):
        db.remove_car(car.id)
