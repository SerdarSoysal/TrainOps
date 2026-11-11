"""Step 7: train planning."""

import random
import shutil
from dataclasses import replace

import pytest

from trainops import planning as p
from trainops import vocab as v
from trainops.coldstart import cold_start
from trainops.config import load_config, parse_config
from trainops.db import Car, Database, Engine, SpotState
from trainops.planning import engines_needed, make_plan, plan_day

YARD_PLACES = {v.EASTBOUND_TRACK, v.WESTBOUND_TRACK, v.LOCALS_TRACK}


def fixed_in(spot_id="pit", **changes):
    spot = {
        "spot_id": spot_id,
        "name": spot_id.title(),
        "requirement_mode": "fixed",
        "car_type": "covered hopper",
        "direction": "incoming",
        "source": "West",
        "base_processing_days": 2,
    }
    spot.update(changes)
    return spot


def fixed_out(spot_id="door", **changes):
    spot = {
        "spot_id": spot_id,
        "name": spot_id.title(),
        "requirement_mode": "fixed",
        "car_type": "boxcar",
        "direction": "outgoing",
        "pattern": ["East"],
        "base_processing_days": 2,
    }
    spot.update(changes)
    return spot


class Layout:
    """A small railroad built by hand: spots, cars and engines as records."""

    def __init__(self, *spot_dicts, industries=None, **settings):
        if industries is None:
            industries = [{"id": "mill", "name": "Mill", "spots": list(spot_dicts)}]
        self.config = parse_config({"settings": settings, "industries": industries})
        self.cars: list[Car] = []
        self.engines: list[Engine] = []
        # Default: every spot busy (no demand today or tomorrow).
        self.states = {
            s.spot_id: self.spot_state(s.spot_id, v.PROCESSING, days_left=5)
            for s in self.config.spots
        }
        for _ in range(6):
            self.engine(v.POOL_MANIFEST, v.STORAGE)
        for _ in range(2):
            self.engine(v.POOL_LOCAL, v.STORAGE)

    @staticmethod
    def spot_state(spot_id, state, **fields):
        base = SpotState(spot_id=spot_id, state=state, industry_id="mill", identity="test")
        return replace(base, **{"next_delay": False, "waiting_since_day": 1, **fields})

    def set_spot(self, spot_id, state, **fields):
        self.states[spot_id] = self.spot_state(spot_id, state, **fields)

    def car(self, car_type, where, **fields):
        if where in v.WORLDS:
            kind, seq = v.AT_WORLD, None
        elif where in YARD_PLACES:
            kind, seq = v.AT_YARD, len(self.cars) + 1
        else:
            kind, seq = v.AT_SPOT, None
        record = dict(
            id=len(self.cars) + 1,
            mark="TEST",
            number=str(len(self.cars) + 1),
            type=car_type,
            loc_kind=kind,
            loc_ref=where,
            seq=seq,
            load=v.NOT_TRACKED,
            last_loaded_industry=None,
            origin_world=v.WEST_STAGING,
            assigned_spot=None,
            dest_world=None,
            days_held=0,
            bad_order=False,
        )
        record.update(fields)
        car = Car(**record)
        self.cars.append(car)
        return car

    def cars_of(self, car_type, where, count, **fields):
        return [self.car(car_type, where, **fields) for _ in range(count)]

    def engine(self, pool, where):
        kind = v.AT_STORAGE if where == v.STORAGE else v.AT_WORLD
        engine = Engine(len(self.engines) + 1, "ENG", str(len(self.engines) + 1), None, pool,
                        kind, where, None)
        self.engines.append(engine)
        return engine

    def plan(self, day=5, seed=1):
        return make_plan(self.config, day, self.states, self.cars, self.engines,
                         random.Random(seed))


def supply_of(plan, spot_id, when="today"):
    supplies = plan.today_supply if when == "today" else plan.tomorrow_supply
    return next(s for s in supplies if s.demand.spot_id == spot_id)


# --- today -----------------------------------------------------------------------------


def test_east_incoming_demand_gets_a_loaded_car_from_the_east_loop():
    lay = Layout(fixed_in(source="East"))
    lay.set_spot("pit", v.AWAITING_CAR)
    lay.car("boxcar", v.EAST_STAGING)
    hopper = lay.car("covered hopper", v.EAST_STAGING)
    plan = lay.plan()

    assert supply_of(plan, "pit") == p.Supply(plan.today.demands[0], hopper.id, p.WESTBOUND_BLOCK)
    assert plan.assignments == {hopper.id: ("pit", v.LOADED)}
    assert plan.westbound.block_ids == (hopper.id,)
    assert plan.westbound.car_ids[-1] == hopper.id  # Local block at the rear
    assert plan.local.car_ids == (hopper.id,)
    assert plan.local_has_work


def test_outgoing_demand_takes_the_longest_held_empty_before_the_east_loop():
    lay = Layout(fixed_out())
    lay.set_spot("door", v.AWAITING_CAR)
    lay.car("boxcar", v.LOCALS_TRACK, load=v.EMPTY, days_held=0)
    older = lay.car("boxcar", v.LOCALS_TRACK, load=v.EMPTY, days_held=1)
    lay.car("boxcar", v.EAST_STAGING)
    plan = lay.plan()

    assert supply_of(plan, "door").car_id == older.id
    assert supply_of(plan, "door").source == p.HELD_EMPTY
    assert plan.westbound.block_ids == ()
    assert plan.assignments == {older.id: ("door", v.EMPTY)}


def test_car_already_assigned_on_locals_covers_its_spot():
    lay = Layout(fixed_in())
    lay.set_spot("pit", v.AWAITING_CAR)
    waiting = lay.car("covered hopper", v.LOCALS_TRACK, load=v.LOADED, assigned_spot="pit")
    plan = lay.plan()

    assert supply_of(plan, "pit").source == p.ALREADY_ON_LOCALS
    assert plan.assignments == {}
    assert plan.local.car_ids == (waiting.id,)
    assert plan.notes == ()


def test_return_to_shipper_a_car_never_comes_back_loaded_to_the_industry_that_loaded_it():
    lay = Layout(fixed_in(source="East"))
    lay.set_spot("pit", v.AWAITING_CAR)
    lay.car("covered hopper", v.EAST_STAGING, last_loaded_industry="mill")
    plan = lay.plan()
    assert supply_of(plan, "pit").car_id is None

    lay = Layout(fixed_out(car_type="covered hopper"))
    lay.set_spot("door", v.AWAITING_CAR)
    hopper = lay.car("covered hopper", v.EAST_STAGING, last_loaded_industry="mill")
    assert supply_of(lay.plan(), "door").car_id == hopper.id  # empty is fine


def test_west_supplied_demand_today_with_nothing_on_locals_waits():
    lay = Layout(fixed_in())
    lay.set_spot("pit", v.AWAITING_CAR)
    lay.car("covered hopper", v.WEST_STAGING)
    lay.car("covered hopper", v.EAST_STAGING)
    plan = lay.plan()

    assert supply_of(plan, "pit").car_id is None
    assert "No car for Mill, Pit today: needs a loaded covered hopper from the West." in plan.notes
    # Still waiting tomorrow, so the Eastbound Local block brings one.
    assert supply_of(plan, "pit", "tomorrow").source == p.EASTBOUND_BLOCK


def test_ready_spot_without_idle_is_refilled_on_the_same_visit():
    lay = Layout(fixed_in(source="East"))
    lay.set_spot("pit", v.READY_FOR_PICKUP)
    lay.car("covered hopper", "pit", load=v.LOADED)
    new = lay.car("covered hopper", v.EAST_STAGING)
    plan = lay.plan()
    assert supply_of(plan, "pit").car_id == new.id
    assert supply_of(plan, "pit").demand.swap


# --- tomorrow --------------------------------------------------------------------------


def test_tomorrows_west_demand_rides_in_the_eastbound_local_block():
    lay = Layout(fixed_in())
    lay.set_spot("pit", v.IDLE, days_left=1)
    lay.cars_of("boxcar", v.WEST_STAGING, 5)
    hopper = lay.car("covered hopper", v.WEST_STAGING)
    plan = lay.plan()

    assert supply_of(plan, "pit", "tomorrow") == p.Supply(
        plan.tomorrow.demands[0], hopper.id, p.EASTBOUND_BLOCK
    )
    assert plan.assignments == {hopper.id: ("pit", v.LOADED)}
    assert plan.eastbound.block_ids == (hopper.id,)
    assert plan.eastbound.car_ids[-1] == hopper.id


def test_tomorrows_east_demand_rides_east_as_a_continuing_car():
    lay = Layout(fixed_in(source="East"))
    lay.set_spot("pit", v.IDLE, days_left=1)
    lay.cars_of("boxcar", v.WEST_STAGING, 5)
    hopper = lay.car("covered hopper", v.WEST_STAGING)
    plan = lay.plan(seed=4)

    assert supply_of(plan, "pit", "tomorrow").car_id == hopper.id
    assert supply_of(plan, "pit", "tomorrow").source == p.EAST_SUPPLY
    assert hopper.id in plan.eastbound.car_ids
    assert plan.eastbound.block_ids == ()
    assert plan.assignments == {}  # assigned tomorrow, from the East loop
    assert plan.eastbound_minimum == 1


def test_tomorrows_east_demand_can_be_met_by_the_eastbound_pickup():
    lay = Layout(
        industries=[
            {"id": "mill", "name": "Mill", "spots": [fixed_out(idle_days=2)]},
            {"id": "shed", "name": "Shed", "spots": [fixed_in("shed_door", car_type="boxcar",
                                                              source="East")]},
        ]
    )
    lay.set_spot("door", v.READY_FOR_PICKUP, out_dest=v.EAST)
    loaded = lay.car("boxcar", "door", load=v.EMPTY)
    lay.set_spot("shed_door", v.IDLE, days_left=1)
    lay.cars_of("boxcar", v.WEST_STAGING, 3)
    plan = lay.plan()

    assert loaded.id in plan.eastbound_pickup
    assert supply_of(plan, "shed_door", "tomorrow").car_id == loaded.id
    assert supply_of(plan, "shed_door", "tomorrow").source == p.EASTBOUND_PICKUP
    assert plan.eastbound_minimum == 0


def test_pickup_car_loaded_here_cant_come_back_loaded_here():
    lay = Layout(fixed_out(idle_days=1), fixed_in("ramp", car_type="boxcar", source="East"))
    lay.set_spot("door", v.READY_FOR_PICKUP, out_dest=v.EAST)
    lay.car("boxcar", "door")
    lay.set_spot("ramp", v.IDLE, days_left=1)
    other = lay.car("boxcar", v.WEST_STAGING)
    plan = lay.plan()
    assert supply_of(plan, "ramp", "tomorrow").car_id == other.id
    assert supply_of(plan, "ramp", "tomorrow").source == p.EAST_SUPPLY


def test_empty_pulled_today_is_held_for_tomorrows_outgoing_spot():
    lay = Layout(fixed_in(idle_days=2), fixed_out("loader", car_type="covered hopper",
                                                  pattern=["West"]))
    lay.set_spot("pit", v.READY_FOR_PICKUP)
    unloaded = lay.car("covered hopper", "pit", load=v.LOADED, origin_world=v.EAST_STAGING)
    lay.set_spot("loader", v.IDLE, days_left=1)
    lay.cars_of("covered hopper", v.WEST_STAGING, 3)
    plan = lay.plan()

    assert supply_of(plan, "loader", "tomorrow").source == p.HELD_EMPTY_TOMORROW
    assert supply_of(plan, "loader", "tomorrow").car_id == unloaded.id
    assert plan.eastbound.block_ids == ()
    assert unloaded.id not in plan.eastbound_pickup


def test_with_no_holding_an_unloaded_car_goes_home():
    lay = Layout(fixed_in(idle_days=1), fixed_out("loader", car_type="covered hopper"),
                 hold_days_on_locals=0)
    lay.set_spot("pit", v.READY_FOR_PICKUP)
    unloaded = lay.car("covered hopper", "pit", load=v.LOADED, origin_world=v.EAST_STAGING)
    assert lay.plan().eastbound_pickup == (unloaded.id,)


def test_bad_order_car_goes_west_not_east():
    lay = Layout(fixed_out(idle_days=1))
    lay.set_spot("door", v.PROCESSING, days_left=2)
    broken = lay.car("boxcar", "door", bad_order=True, origin_world=v.EAST_STAGING)
    replacement = lay.car("boxcar", v.EAST_STAGING)
    plan = lay.plan()
    assert broken.id not in plan.eastbound_pickup
    assert supply_of(plan, "door").car_id == replacement.id  # the bad-order pull frees the spot
    assert plan.local_has_work


# --- the Locals track ------------------------------------------------------------------


def test_car_no_longer_wanted_is_released_and_goes_home():
    lay = Layout(fixed_in())
    stray = lay.car("boxcar", v.LOCALS_TRACK, load=v.LOADED, assigned_spot="pit")
    plan = lay.plan()
    assert plan.released == (stray.id,)
    assert plan.going_home == (stray.id,)
    assert "TEST 1 on the Locals track is no longer wanted at Mill, Pit." in plan.notes


def test_released_empty_of_a_useful_type_becomes_a_held_empty():
    lay = Layout(fixed_in(), fixed_out())
    lay.set_spot("door", v.AWAITING_CAR)
    stray = lay.car("boxcar", v.LOCALS_TRACK, load=v.EMPTY, assigned_spot="pit")
    plan = lay.plan()
    assert plan.released == (stray.id,) and plan.going_home == ()
    assert supply_of(plan, "door").car_id == stray.id
    assert plan.assignments[stray.id] == ("door", v.EMPTY)


def test_car_waiting_for_a_random_spots_next_draw_is_kept():
    team = {
        "spot_id": "team",
        "name": "Team",
        "requirement_mode": "random",
        "possible_requirements": [
            {"car_type": "boxcar", "direction": "incoming", "source_weights": {"East": 1},
             "base_processing_days": 2},
            {"car_type": "tank car", "direction": "outgoing",
             "destination_weights": {"West": 1}, "base_processing_days": 2},
        ],
    }
    lay = Layout(team)
    lay.set_spot("team", v.PROCESSING, days_left=2, requirement_number=1,
                 requirement_side=v.EAST, next_requirement_number=2, next_requirement_side=v.WEST)
    kept = lay.car("tank car", v.LOCALS_TRACK, load=v.EMPTY, assigned_spot="team")
    plan = lay.plan()
    assert plan.released == () and plan.going_home == ()
    assert kept.id not in plan.local.car_ids  # not needed today


def test_held_empties_go_home_after_the_hold_days():
    lay = Layout(fixed_out(), hold_days_on_locals=2)
    lay.set_spot("door", v.IDLE, days_left=1)
    expired = lay.car("boxcar", v.LOCALS_TRACK, load=v.EMPTY, days_held=3,
                      origin_world=v.EAST_STAGING)
    last_day = lay.car("boxcar", v.LOCALS_TRACK, load=v.EMPTY, days_held=2)
    lay.cars_of("boxcar", v.WEST_STAGING, 2)
    plan = lay.plan()
    assert plan.going_home == (expired.id,)
    assert expired.id in plan.eastbound_pickup  # the Local return job sends it toward the East
    # last_day can't wait until tomorrow (and leaves at tomorrow's Local return job), so tomorrow's
    # need is met by the expired empty riding East today.
    assert last_day.id not in plan.eastbound_pickup
    assert supply_of(plan, "door", "tomorrow").car_id == expired.id
    assert supply_of(plan, "door", "tomorrow").source == p.EASTBOUND_PICKUP


# --- trains ----------------------------------------------------------------------------


def test_westbound_carries_the_whole_east_loop():
    lay = Layout(fixed_in())
    east = lay.cars_of("gondola", v.EAST_STAGING, 9)
    plan = lay.plan()
    assert sorted(plan.westbound.car_ids) == [c.id for c in east]
    assert plan.westbound.arriving == plan.westbound.departing == 9


@pytest.mark.parametrize("seed", range(10))
def test_eastbound_length_is_drawn_between_min_and_max(seed):
    lay = Layout(fixed_in())
    lay.cars_of("gondola", v.WEST_STAGING, 30)
    plan = lay.plan(seed=seed)
    assert 12 <= plan.eastbound_draw <= 20
    assert plan.eastbound.arriving == len(plan.eastbound.car_ids) == plan.eastbound_draw
    assert len(set(plan.eastbound.car_ids)) == plan.eastbound.arriving


def test_eastbound_is_raised_to_its_minimum():
    lay = Layout(fixed_in("a"), fixed_in("b"), fixed_in("c", source="East"),
                 eastbound_length_min=1, eastbound_length_max=1)
    for spot_id in "abc":
        lay.set_spot(spot_id, v.IDLE, days_left=1)
    lay.cars_of("covered hopper", v.WEST_STAGING, 10)
    plan = lay.plan()
    assert plan.eastbound_minimum == 3
    assert plan.eastbound.arriving == 3
    assert len(plan.eastbound.block_ids) == 2


def test_eastbound_is_lowered_to_what_west_staging_holds():
    lay = Layout(fixed_in())
    lay.cars_of("gondola", v.WEST_STAGING, 5)
    assert lay.plan().eastbound.arriving == 5


def test_engines_by_length():
    settings = Layout(fixed_in()).config.settings
    assert engines_needed(15, 12, settings) == 2
    assert engines_needed(12, 16, settings) == 3
    assert engines_needed(16, 12, settings) == 3


def test_overload_train_when_over_twenty_cars():
    lay = Layout(fixed_in(), three_engines_from=25)
    lay.cars_of("gondola", v.EAST_STAGING, 22)
    plan = lay.plan()
    assert plan.westbound.overload
    assert len(plan.westbound.engine_ids) == 3  # an overload always gets 3


def test_manifest_engines_come_from_their_world_or_storage():
    lay = Layout(fixed_in())
    lay.engines = []
    at_east = [lay.engine(v.POOL_MANIFEST, v.EAST_STAGING) for _ in range(2)]
    at_west = [lay.engine(v.POOL_MANIFEST, v.WEST_STAGING) for _ in range(2)]
    stored = [lay.engine(v.POOL_MANIFEST, v.STORAGE) for _ in range(2)]
    local = [lay.engine(v.POOL_LOCAL, v.STORAGE) for _ in range(3)]
    lay.cars_of("gondola", v.EAST_STAGING, 16)  # 3 engines
    lay.cars_of("gondola", v.WEST_STAGING, 30)
    for seed in range(10):
        plan = lay.plan(seed=seed)
        wb, eb = set(plan.westbound.engine_ids), set(plan.eastbound.engine_ids)
        assert len(wb) == 3 and len(eb) == plan.eastbound.engine_ids.__len__()
        assert wb <= {e.id for e in at_east + stored}
        assert eb <= {e.id for e in at_west + stored}
        assert not wb & eb
        assert len(plan.local.engine_ids) == 2
        assert set(plan.local.engine_ids) <= {e.id for e in local}


def test_short_of_engines_is_noted():
    lay = Layout(fixed_in())
    lay.engines = [lay.engine(v.POOL_MANIFEST, v.WEST_STAGING)]
    plan = lay.plan()
    assert plan.westbound.engine_ids == ()
    assert "The westbound manifest needs 2 engines but only 0 are in East staging or Storage." \
        in plan.notes


def test_westbound_pickup_waits_only_when_west_staging_would_overflow():
    lay = Layout(fixed_in(), capacity={"west_staging": 14})
    lay.cars_of("gondola", v.WEST_STAGING, 10)
    lay.cars_of("gondola", v.EAST_STAGING, 3)
    track = lay.cars_of("gondola", v.WESTBOUND_TRACK, 2)
    plan = lay.plan()
    assert plan.westbound_pickup == (track[0].id,)  # oldest first
    assert "West staging is nearly full: 1 cars wait on the Westbound track until tomorrow." \
        in plan.notes

    lay.config = parse_config({"industries": [{"id": "mill", "name": "Mill",
                                                "spots": [fixed_in()]}]})
    assert lay.plan().westbound_pickup == tuple(c.id for c in track)


def test_eastbound_pickup_waits_only_when_the_east_loop_would_overflow():
    lay = Layout(fixed_in(), eastbound_length_min=10, eastbound_length_max=10,
                 capacity={"east_staging": 12})
    lay.cars_of("gondola", v.WEST_STAGING, 10)
    track = lay.cars_of("gondola", v.EASTBOUND_TRACK, 4)
    plan = lay.plan()
    assert plan.eastbound_pickup == (track[0].id, track[1].id)
    assert plan.eastbound.departing == 12
    assert any("The East loop is nearly full: 2 cars" in n for n in plan.notes)


def test_no_local_work():
    lay = Layout(fixed_in())
    assert not lay.plan().local_has_work


# --- the sample railroad, through the database -----------------------------------------


@pytest.fixture
def sample_db(tmp_path, samples_dir):
    config = load_config(samples_dir / "config.yaml")
    cars, engines = tmp_path / "cars.csv", tmp_path / "engines.csv"
    shutil.copy(samples_dir / "cars.csv", cars)
    shutil.copy(samples_dir / "engines.csv", engines)
    db = Database.open(":memory:")
    cold_start(db, config, cars, engines, rng=random.Random(7))
    yield db, config
    db.close()


def test_plan_day_writes_the_consist_plans(sample_db):
    db, config = sample_db
    with db.transaction():
        plan = plan_day(db, config, random.Random(3))

    for train in (v.WESTBOUND_MANIFEST, v.EASTBOUND_MANIFEST, v.LOCAL):
        entries = db.consist_plan(train)
        tp = plan.train(train)
        engines = [e.engine_id for e in entries if e.engine_id is not None]
        cars = [e.car_id for e in entries if e.car_id is not None]
        assert entries[: len(engines)] == [e for e in entries if e.engine_id]  # engines lead
        assert tuple(engines) == tp.engine_ids and tuple(cars) == tp.car_ids
        if tp.block_ids:
            assert tuple(cars[-len(tp.block_ids):]) == tp.block_ids  # block at the rear

    east = {c.id for c in db.cars_at(v.AT_WORLD, v.EAST_STAGING)}
    west = {c.id for c in db.cars_at(v.AT_WORLD, v.WEST_STAGING)}
    assert set(plan.westbound.car_ids) == east
    assert set(plan.eastbound.car_ids) <= west
    assert set(plan.local.car_ids) <= set(plan.westbound.block_ids)  # day 1: yard empty
    for car_id, (spot_id, load) in plan.assignments.items():
        car = db.car(car_id)
        assert (car.assigned_spot, car.load) == (spot_id, load)
    assert db.session().local_has_work == plan.local_has_work


def test_plan_day_clears_old_assignments_in_the_worlds(sample_db):
    db, config = sample_db
    gondola = db.find_car("CSXT", "491022")
    with db.transaction():
        db.update_car(gondola.id, assigned_spot="harbor_pit", load=v.LOADED)
        plan_day(db, config, random.Random(3))
    gondola = db.car(gondola.id)
    assert (gondola.assigned_spot, gondola.load) == (None, v.NOT_TRACKED)


def test_day_one_plan_covers_east_and_west_demand(sample_db):
    db, config = sample_db
    with db.transaction():
        plan = plan_day(db, config, random.Random(3))
    # Day 1: every spot is waiting. East-supplied ones are served from the East loop;
    # West-supplied ones can't be (nothing on Locals yet) and are planned for tomorrow.
    for supply in plan.today_supply:
        if supply.demand.side == v.EAST:
            assert supply.source in (p.WESTBOUND_BLOCK, None)
        else:
            assert supply.car_id is None
    west_today = {s.demand.spot_id for s in plan.today_supply if s.demand.side == v.WEST}
    tomorrow = {s.demand.spot_id: s for s in plan.tomorrow_supply}
    for spot_id in west_today:
        assert tomorrow[spot_id].source == p.EASTBOUND_BLOCK


@pytest.mark.parametrize("seed", range(25))
def test_sample_plans_keep_every_car_in_one_place(sample_db, seed):
    db, config = sample_db
    with db.transaction():
        plan = plan_day(db, config, random.Random(seed))
    wb, eb, local = (set(t.car_ids) for t in (plan.westbound, plan.eastbound, plan.local))
    assert not wb & eb
    assert local <= set(plan.westbound.block_ids) | {
        c.id for c in db.cars_at(v.AT_YARD, v.LOCALS_TRACK)
    }
    assert len(plan.westbound.engine_ids) == engines_needed(
        plan.westbound.arriving, plan.westbound.departing, config.settings
    )
    assert len(plan.eastbound.engine_ids) == engines_needed(
        plan.eastbound.arriving, plan.eastbound.departing, config.settings
    )
    assert config.settings.eastbound_length_min <= plan.eastbound.arriving <= max(
        config.settings.eastbound_length_max, plan.eastbound_minimum
    )
    assert len({s.demand.spot_id for s in plan.today_supply}) == len(plan.today_supply)
