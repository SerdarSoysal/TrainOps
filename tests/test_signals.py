"""Step 8: signals and the daily sequence."""

import random
import shutil
from collections import Counter

import pytest
import yaml

from trainops import vocab as v
from trainops.coldstart import cold_start
from trainops.config import load_config
from trainops.db import Database
from trainops.planning import outgoing_types
from trainops.roster import retire_car
from trainops.signals import SignalRefused, current_job, handle


@pytest.fixture
def railroad(tmp_path, samples_dir):
    config = load_config(samples_dir / "config.yaml")
    cars, engines = tmp_path / "cars.csv", tmp_path / "engines.csv"
    shutil.copy(samples_dir / "cars.csv", cars)
    shutil.copy(samples_dir / "engines.csv", engines)
    db = Database.open(":memory:")
    cold_start(db, config, cars, engines, rng=random.Random(5))
    yield db, config
    db.close()


def send(db, config, signal, spot_id=None, seed=0):
    return handle(db, config, signal, spot_id, random.Random(seed))


def to_the_local(db, config):
    send(db, config, v.WEST_CHORE_DONE)
    send(db, config, v.EAST_CHORE_DONE)
    send(db, config, v.SWITCH_WESTBOUND_DONE)


def local_moves(db):
    """(pulls, set-outs) the local can do now."""
    states = db.spot_states()
    pulls = [c.loc_ref for c in db.cars()
             if c.loc_kind == v.AT_SPOT
             and (c.bad_order or states[c.loc_ref].state == v.READY_FOR_PICKUP)]
    setouts = [c.assigned_spot for c in db.cars_at(v.AT_TRAIN, v.LOCAL)]
    return pulls, setouts


def run_local(db, config, rng, skip_chance=0.0):
    pulls, setouts = local_moves(db)
    pulled = set()
    for spot_id in pulls:
        if rng.random() >= skip_chance:
            send(db, config, v.PULL_DONE, spot_id)
            pulled.add(spot_id)
    for spot_id in setouts:
        occupied = db.cars_at(v.AT_SPOT, spot_id)
        if not occupied and rng.random() >= skip_chance:
            send(db, config, v.SET_OUT_DONE, spot_id)


def finish_day(db, config, seed):
    if not db.session().local_back:
        send(db, config, v.LOCAL_BACK)
    send(db, config, v.LOCAL_RETURN_DONE)
    send(db, config, v.SWITCH_EASTBOUND_DONE)
    return send(db, config, v.SESSION_COMPLETE, seed=seed)


def run_day(db, config, rng, skip_chance=0.0):
    to_the_local(db, config)
    if not db.session().local_back:
        run_local(db, config, rng, skip_chance)
    return finish_day(db, config, rng.randrange(10**6))


def check_invariants(db, config):
    cars = db.cars()
    states = db.spot_states()
    # Between sessions nothing is on a train, and the local's engines are put away.
    assert not [c for c in cars if c.loc_kind == v.AT_TRAIN]
    assert not db.engines_at(v.AT_TRAIN, v.LOCAL)
    # A spot holds a car exactly while it is processing or ready.
    at_spot = Counter(c.loc_ref for c in cars if c.loc_kind == v.AT_SPOT)
    for spot_id, state in states.items():
        busy = state.state in (v.PROCESSING, v.READY_FOR_PICKUP)
        assert at_spot[spot_id] == (1 if busy else 0), (spot_id, state)
    # Cars in the worlds are untracked, except tomorrow's planned Local block cars,
    # which got their spot and load when they were chosen. Capacities hold.
    planned = {e.car_id for t in v.TRAINS for e in db.consist_plan(t)}
    for c in cars:
        if c.loc_kind == v.AT_WORLD:
            assert c.dest_world is None
            if c.load != v.NOT_TRACKED or c.assigned_spot:
                assert c.assigned_spot and c.id in planned
    s = config.settings.capacity
    assert len(db.cars_at(v.AT_WORLD, v.EAST_STAGING)) <= s.east_staging
    assert len(db.cars_at(v.AT_WORLD, v.WEST_STAGING)) <= s.west_staging
    # The Locals track: assigned cars, or empties still within their hold days.
    held_types = outgoing_types(config)
    for c in db.cars_at(v.AT_YARD, v.LOCALS_TRACK):
        if c.assigned_spot is None:
            assert c.load == v.EMPTY and any(v.same_words(c.type, t) for t in held_types)
            assert c.days_held <= config.settings.hold_days_on_locals + 1
    # The Eastbound track is always taken by Switch eastbound.
    assert db.cars_at(v.AT_YARD, v.EASTBOUND_TRACK) == []


# --- order -----------------------------------------------------------------------------


def test_signals_are_taken_in_order(railroad):
    db, config = railroad
    assert current_job(db.session()) == v.JOB_CHORES
    with pytest.raises(SignalRefused, match="^Waiting on the West chore and the East chore.$"):
        send(db, config, v.SWITCH_WESTBOUND_DONE)
    send(db, config, v.WEST_CHORE_DONE)
    with pytest.raises(SignalRefused, match="^The West chore is already done.$"):
        send(db, config, v.WEST_CHORE_DONE)
    with pytest.raises(SignalRefused, match="^Waiting on the East chore.$"):
        send(db, config, v.PULL_DONE, "harbor_pit")
    send(db, config, v.EAST_CHORE_DONE)
    assert current_job(db.session()) == v.SWITCH_WESTBOUND
    with pytest.raises(SignalRefused, match="^Waiting on Switch westbound.$"):
        send(db, config, v.LOCAL_BACK)
    send(db, config, "  switch WESTBOUND   done ")  # capitals and spaces don't matter
    assert current_job(db.session()) == v.JOB_LOCAL
    with pytest.raises(SignalRefused, match="^Waiting on the local.$"):
        send(db, config, v.LOCAL_RETURN_DONE)
    send(db, config, v.LOCAL_BACK)
    with pytest.raises(SignalRefused, match="^The local is already back in the yard.$"):
        send(db, config, v.SET_OUT_DONE, "harbor_pit")
    with pytest.raises(SignalRefused, match="^Waiting on the Local return job.$"):
        send(db, config, v.SESSION_COMPLETE)
    send(db, config, v.LOCAL_RETURN_DONE)
    assert current_job(db.session()) == v.SWITCH_EASTBOUND
    send(db, config, v.SWITCH_EASTBOUND_DONE)
    assert current_job(db.session()) == v.JOB_END
    notes = send(db, config, v.SESSION_COMPLETE)
    assert notes[0] == "Day 2 begins."
    assert current_job(db.session()) == v.JOB_CHORES


def test_unknown_signal_and_missing_spot_are_refused(railroad):
    db, config = railroad
    with pytest.raises(SignalRefused, match="'Lunch' is not a signal"):
        send(db, config, "Lunch")
    with pytest.raises(SignalRefused, match="Pull done needs a spot; 'nowhere' is not one."):
        send(db, config, v.PULL_DONE, "nowhere")


def test_a_refused_signal_changes_nothing(railroad):
    db, config = railroad
    to_the_local(db, config)
    before = (db.cars(), db.spot_states(), db.session())
    with pytest.raises(SignalRefused):
        send(db, config, v.PULL_DONE, "harbor_pit")  # nothing there yet
    assert (db.cars(), db.spot_states(), db.session()) == before


# --- the chores and Switch westbound --------------------------------------------------------------


def test_chores_build_the_manifests_from_the_plan(railroad):
    db, config = railroad
    wb_plan = db.consist_plan(v.WESTBOUND_MANIFEST)
    send(db, config, v.EAST_CHORE_DONE)
    train = db.cars_at(v.AT_TRAIN, v.WESTBOUND_MANIFEST)
    assert [c.id for c in train] == [e.car_id for e in wb_plan if e.car_id]
    assert db.cars_at(v.AT_WORLD, v.EAST_STAGING) == []
    engines = db.engines_at(v.AT_TRAIN, v.WESTBOUND_MANIFEST)
    assert [e.id for e in engines] == [e.engine_id for e in wb_plan if e.engine_id]
    # Spare engines left in the East loop went to Storage.
    assert db.engines_at(v.AT_WORLD, v.EAST_STAGING) == []


def test_switch_westbound_cuts_the_block_and_the_train_reaches_west_staging(railroad):
    db, config = railroad
    block = {c.id for c in db.cars() if c.assigned_spot and c.loc_ref == v.EAST_STAGING}
    wb = {c.id for c in db.cars_at(v.AT_WORLD, v.EAST_STAGING)}
    to_the_local(db, config)
    local = db.cars_at(v.AT_TRAIN, v.LOCAL)
    assert {c.id for c in local} == block  # block went to Locals, then onto the local
    west = {c.id for c in db.cars_at(v.AT_WORLD, v.WEST_STAGING)}
    assert wb - block <= west
    assert all(db.car(i).load == v.NOT_TRACKED for i in wb - block)
    assert len(db.engines_at(v.AT_TRAIN, v.LOCAL)) == 2


# --- the local -------------------------------------------------------------------------


def test_set_out_and_pull_change_car_and_spot(railroad):
    db, config = railroad
    to_the_local(db, config)
    car = db.cars_at(v.AT_TRAIN, v.LOCAL)[0]
    spot_id = car.assigned_spot
    assert send(db, config, v.SET_OUT_DONE, spot_id) == [
        f"Spotted {car.label} at {config.spot(spot_id).label}."
    ]
    car = db.car(car.id)
    assert (car.loc_kind, car.loc_ref, car.assigned_spot) == (v.AT_SPOT, spot_id, None)
    assert db.spot_state(spot_id).state == v.PROCESSING
    with pytest.raises(SignalRefused, match="No car on the local is for"):
        send(db, config, v.SET_OUT_DONE, spot_id)
    with pytest.raises(SignalRefused, match="processing"):
        send(db, config, v.PULL_DONE, spot_id)


def test_outgoing_pull_loads_the_car_for_its_destination(railroad):
    db, config = railroad
    # Run days until a loaded car is pulled from an outgoing spot.
    rng = random.Random(1)
    for _ in range(10):
        to_the_local(db, config)
        pulls, _ = local_moves(db)
        for spot_id in pulls:
            state = db.spot_state(spot_id)
            car = db.cars_at(v.AT_SPOT, spot_id)[0]
            send(db, config, v.PULL_DONE, spot_id)
            if state.out_dest:
                car = db.car(car.id)
                assert car.load == v.LOADED
                assert car.dest_world == (v.EAST_STAGING if state.out_dest == v.EAST
                                          else v.WEST_STAGING)
                assert car.last_loaded_industry == config.spot(spot_id).industry_id
                return
        run_local(db, config, rng)
        finish_day(db, config, seed=rng.randrange(1000))
    pytest.fail("no outgoing pull in 10 days")


def test_swap_set_out_waits_for_the_pull(railroad):
    db, config = railroad
    rng = random.Random(2)
    for _ in range(15):
        to_the_local(db, config)
        pulls, setouts = local_moves(db)
        both = set(pulls) & set(setouts)
        if both:
            spot_id = both.pop()
            occupant = db.cars_at(v.AT_SPOT, spot_id)[0]
            with pytest.raises(SignalRefused, match=f"Pull {occupant.label} from .* first."):
                send(db, config, v.SET_OUT_DONE, spot_id)
            send(db, config, v.PULL_DONE, spot_id)
            send(db, config, v.SET_OUT_DONE, spot_id)
            return
        run_local(db, config, rng)
        finish_day(db, config, seed=rng.randrange(1000))
    pytest.fail("no same-visit swap in 15 days")


def test_undelivered_car_returns_to_locals_and_goes_out_again(railroad):
    db, config = railroad
    to_the_local(db, config)
    car = db.cars_at(v.AT_TRAIN, v.LOCAL)[0]
    notes = send(db, config, v.LOCAL_BACK)
    assert car.label in notes[0] and notes[0].startswith("Not delivered")
    send(db, config, v.LOCAL_RETURN_DONE)
    back = db.car(car.id)
    assert (back.loc_ref, back.assigned_spot, back.load) == (
        v.LOCALS_TRACK, car.assigned_spot, car.load)
    send(db, config, v.SWITCH_EASTBOUND_DONE)
    send(db, config, v.SESSION_COMPLETE)
    to_the_local(db, config)
    assert db.car(car.id).loc_ref == v.LOCAL  # first in line next run


def test_unpulled_car_stays_ready_with_its_destination(railroad):
    db, config = railroad
    rng = random.Random(3)
    for _ in range(10):
        to_the_local(db, config)
        pulls, _ = local_moves(db)
        if pulls:
            spot_id = pulls[0]
            state = db.spot_state(spot_id)
            car = db.cars_at(v.AT_SPOT, spot_id)[0]
            finish_day(db, config, seed=1)  # the local did nothing
            assert db.cars_at(v.AT_SPOT, spot_id)[0].id == car.id
            assert db.spot_state(spot_id).state == v.READY_FOR_PICKUP
            assert db.spot_state(spot_id).out_dest == state.out_dest
            return
        run_local(db, config, rng)
        finish_day(db, config, seed=rng.randrange(1000))
    pytest.fail("no pull in 10 days")


# --- Bad order -------------------------------------------------------------------------


def test_bad_order_car_is_pulled_sent_west_and_leaves_the_roster(railroad):
    db, config = railroad
    rng = random.Random(4)
    run_day(db, config, rng)
    run_day(db, config, rng)
    car = next(c for c in db.cars() if c.loc_kind == v.AT_SPOT)
    spot_id = car.loc_ref
    with db.transaction():
        retire_car(db, config, car)
    state_before = db.spot_state(spot_id)

    to_the_local(db, config)
    assert spot_id in local_moves(db)[0]
    assert send(db, config, v.PULL_DONE, spot_id)[0].endswith("(bad order).")
    if state_before.state == v.PROCESSING:
        after = db.spot_state(spot_id)
        assert after.state == v.AWAITING_CAR
        assert after.waiting_since_day == state_before.waiting_since_day
    send(db, config, v.LOCAL_BACK)
    send(db, config, v.LOCAL_RETURN_DONE)
    assert db.car(car.id).loc_ref == v.WESTBOUND_TRACK
    send(db, config, v.SWITCH_EASTBOUND_DONE)
    send(db, config, v.SESSION_COMPLETE)
    send(db, config, v.WEST_CHORE_DONE)
    send(db, config, v.EAST_CHORE_DONE)
    notes = send(db, config, v.SWITCH_WESTBOUND_DONE)
    assert f"Bad order car {car.label} reached West staging and left the roster" in notes[0]
    assert db.find_car(car.mark, car.number) is None


def test_spot_with_bad_order_car_is_frozen(railroad):
    db, config = railroad
    rng = random.Random(6)
    for _ in range(3):
        run_day(db, config, rng)
    car = next(c for c in db.cars() if c.loc_kind == v.AT_SPOT
               and db.spot_state(c.loc_ref).state == v.PROCESSING)
    with db.transaction():
        retire_car(db, config, car)
    before = db.spot_state(car.loc_ref)
    to_the_local(db, config)
    finish_day(db, config, seed=3)  # the local didn't pull it
    after = db.spot_state(car.loc_ref)
    assert (after.state, after.days_left) == (before.state, before.days_left)


# --- local skipped ---------------------------------------------------------------------


def test_local_is_skipped_when_it_has_no_work(tmp_path, samples_dir):
    data = yaml.safe_load((samples_dir / "config.yaml").read_text())
    data["industries"] = [data["industries"][1]]  # Harbor Feed Mill
    data["industries"][0]["spots"] = [data["industries"][0]["spots"][0]]  # West-supplied pit
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    config = load_config(path)
    db = Database.open(":memory:")
    cold_start(db, config, samples_dir / "cars.csv", samples_dir / "engines.csv",
               rng=random.Random(1))
    send(db, config, v.WEST_CHORE_DONE)
    send(db, config, v.EAST_CHORE_DONE)
    assert "No work for the local today." in send(db, config, v.SWITCH_WESTBOUND_DONE)
    session = db.session()
    assert session.local_back and not session.local_has_work
    assert current_job(session) == v.LOCAL_RETURN
    assert db.engines_at(v.AT_TRAIN, v.LOCAL) == []


# --- whole days ------------------------------------------------------------------------


@pytest.mark.parametrize("skip_chance", [0.0, 0.25])
def test_many_days_keep_the_railroad_consistent(railroad, skip_chance):
    db, config = railroad
    rng = random.Random(11)
    car_count = len(db.cars())
    setouts = Counter()
    for _ in range(60):
        run_day(db, config, rng, skip_chance)
        check_invariants(db, config)
        assert len(db.cars()) == car_count  # nothing lost or duplicated
        for c in db.cars():
            if c.loc_kind == v.AT_SPOT:
                setouts[c.loc_ref] += 1
    assert db.session().day == 61
    assert set(setouts) == set(config.spots_by_id)  # every spot gets used


def test_shortages_clear_up_when_every_move_is_done(railroad):
    db, config = railroad
    rng = random.Random(12)
    shortages = []
    for _ in range(40):
        notes = run_day(db, config, rng)
        shortages.append(sum("today" in n and n.startswith("No car") for n in notes))
    assert sum(shortages[10:]) <= sum(shortages[:10]) + 5


@pytest.mark.parametrize("seed", range(8))
def test_local_moves_are_taken_in_any_order(railroad, seed):
    """Industries and spots in any order; only a set-out on a still-occupied spot waits."""
    db, config = railroad
    rng = random.Random(seed)
    for _ in range(3):
        run_day(db, config, rng)  # get some cars ready for pickup
    to_the_local(db, config)
    pulls, setouts = local_moves(db)
    moves = [(v.PULL_DONE, s) for s in pulls] + [(v.SET_OUT_DONE, s) for s in setouts]
    rng.shuffle(moves)
    waiting = []
    for signal, spot_id in moves:
        try:
            send(db, config, signal, spot_id)
        except SignalRefused as refusal:
            # The one refusal allowed: this spot's own car must be pulled first.
            assert signal == v.SET_OUT_DONE and spot_id in pulls
            assert str(refusal).startswith("Pull ") and str(refusal).endswith(" first.")
            waiting.append(spot_id)
    for spot_id in waiting:  # after their pulls, these go through
        send(db, config, v.SET_OUT_DONE, spot_id)
    assert db.cars_at(v.AT_TRAIN, v.LOCAL) == [
        c for c in db.cars_at(v.AT_TRAIN, v.LOCAL) if c.assigned_spot is None
    ]  # every car for a spot was set out
