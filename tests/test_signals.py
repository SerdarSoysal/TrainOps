"""Step 8: signals and the daily sequence (manifest signals: step 10a feedback)."""

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
from trainops.planning import west_train
from trainops.signals import SignalRefused, handle, open_jobs, set_chore_mode


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
    send(db, config, v.WESTBOUND_IN_YARD)
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
    if not db.session().local_return_done:  # skipped when there is nothing to sort
        send(db, config, v.LOCAL_RETURN_DONE)
    eastbound_home(db, config)
    return send(db, config, v.SESSION_COMPLETE, seed=seed)


def eastbound_home(db, config):
    """From the Local return job done: both manifests to their staging."""
    if not db.session().westbound_in_west_staging:
        send(db, config, v.WESTBOUND_IN_WEST_STAGING)
    send(db, config, v.EASTBOUND_IN_YARD)
    send(db, config, v.SWITCH_EASTBOUND_DONE)
    send(db, config, v.EASTBOUND_IN_EAST_STAGING)


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
    assert open_jobs(db.session()) == [v.JOB_CHORES]
    with pytest.raises(SignalRefused, match="^Waiting on the West chore and the East chore.$"):
        send(db, config, v.WESTBOUND_IN_YARD)
    send(db, config, v.WEST_CHORE_DONE)
    with pytest.raises(SignalRefused, match="^The West chore is already done.$"):
        send(db, config, v.WEST_CHORE_DONE)
    with pytest.raises(SignalRefused, match="^Waiting on the East chore.$"):
        send(db, config, v.PULL_DONE, "harbor_pit")
    send(db, config, v.EAST_CHORE_DONE)
    # Both manifests may leave staging now.
    assert open_jobs(db.session()) == [v.WESTBOUND_TO_YARD, v.EASTBOUND_TO_YARD]
    with pytest.raises(SignalRefused, match="^Waiting on Westbound to yard.$"):
        send(db, config, v.SWITCH_WESTBOUND_DONE)
    send(db, config, v.WESTBOUND_IN_YARD)
    with pytest.raises(SignalRefused, match="^The westbound is already in the yard.$"):
        send(db, config, v.WESTBOUND_IN_YARD)
    assert open_jobs(db.session()) == [v.SWITCH_WESTBOUND, v.EASTBOUND_TO_YARD]
    with pytest.raises(SignalRefused, match="^Waiting on Switch westbound.$"):
        send(db, config, v.LOCAL_BACK)
    with pytest.raises(SignalRefused, match="^Waiting on Switch westbound.$"):
        send(db, config, v.WESTBOUND_IN_WEST_STAGING)
    send(db, config, "  switch WESTBOUND   done ")  # capitals and spaces don't matter
    assert open_jobs(db.session()) == [
        v.WESTBOUND_TO_WEST_STAGING, v.JOB_LOCAL, v.EASTBOUND_TO_YARD]
    with pytest.raises(SignalRefused, match="^Waiting on the local.$"):
        send(db, config, v.LOCAL_RETURN_DONE)
    with pytest.raises(SignalRefused,
                       match="^Waiting on Westbound to West staging and the local.$"):
        send(db, config, v.SESSION_COMPLETE)
    send(db, config, v.LOCAL_BACK)
    with pytest.raises(SignalRefused, match="^The local is already back in the yard.$"):
        send(db, config, v.SET_OUT_DONE, "harbor_pit")
    with pytest.raises(SignalRefused, match="^The eastbound can't enter the yard until the "
                                            "Local return job is done.$"):
        send(db, config, v.EASTBOUND_IN_YARD)
    send(db, config, v.LOCAL_RETURN_DONE)
    with pytest.raises(SignalRefused, match="^Waiting on Eastbound to yard.$"):
        send(db, config, v.SWITCH_EASTBOUND_DONE)
    send(db, config, v.EASTBOUND_IN_YARD)
    send(db, config, v.SWITCH_EASTBOUND_DONE)
    assert open_jobs(db.session()) == [v.WESTBOUND_TO_WEST_STAGING, v.EASTBOUND_TO_EAST_STAGING]
    send(db, config, v.EASTBOUND_IN_EAST_STAGING)
    with pytest.raises(SignalRefused, match="^Waiting on Westbound to West staging.$"):
        send(db, config, v.SESSION_COMPLETE)
    send(db, config, v.WESTBOUND_IN_WEST_STAGING)  # the westbound can be the last one home
    assert open_jobs(db.session()) == [v.JOB_END]
    notes = send(db, config, v.SESSION_COMPLETE)
    assert notes[0] == "Day 2 begins."
    assert open_jobs(db.session()) == [v.JOB_CHORES]
    assert not db.session().westbound_in_yard and not db.session().eastbound_in_east_staging


def test_westbound_reaches_west_staging_while_the_local_works(railroad):
    db, config = railroad
    to_the_local(db, config)
    send(db, config, v.WESTBOUND_IN_WEST_STAGING)
    assert open_jobs(db.session()) == [v.JOB_LOCAL, v.EASTBOUND_TO_YARD]
    run_local(db, config, random.Random(1))
    finish_day(db, config, seed=1)
    check_invariants(db, config)


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
    # The westbound is still on its way to West staging.
    assert {c.id for c in db.cars_at(v.AT_TRAIN, v.WESTBOUND_MANIFEST)} >= wb - block
    send(db, config, v.WESTBOUND_IN_WEST_STAGING)
    assert db.cars_at(v.AT_TRAIN, v.WESTBOUND_MANIFEST) == []
    assert db.engines_at(v.AT_TRAIN, v.WESTBOUND_MANIFEST) == []
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
    eastbound_home(db, config)
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
    eastbound_home(db, config)
    send(db, config, v.SESSION_COMPLETE)
    to_the_local(db, config)
    assert db.car(car.id).loc_ref == v.WESTBOUND_MANIFEST  # on its way west
    notes = send(db, config, v.WESTBOUND_IN_WEST_STAGING)
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
    send(db, config, v.WESTBOUND_IN_YARD)
    notes = send(db, config, v.SWITCH_WESTBOUND_DONE)
    assert notes[-2:] == ["No work for the local today.", "Nothing for the Local return job today."]
    session = db.session()
    assert session.local_back and not session.local_has_work and session.local_return_done
    assert open_jobs(session) == [v.WESTBOUND_TO_WEST_STAGING, v.EASTBOUND_TO_YARD]
    assert db.engines_at(v.AT_TRAIN, v.LOCAL) == []


def test_local_return_job_is_skipped_when_the_local_brings_nothing_back(railroad):
    db, config = railroad
    to_the_local(db, config)
    for car in db.cars_at(v.AT_TRAIN, v.LOCAL):  # deliver everything, pull nothing
        send(db, config, v.SET_OUT_DONE, car.assigned_spot)
    assert db.cars_at(v.AT_YARD, v.LOCALS_TRACK) == []
    notes = send(db, config, v.LOCAL_BACK)
    assert notes == ["Nothing for the Local return job today."]
    assert open_jobs(db.session()) == [v.WESTBOUND_TO_WEST_STAGING, v.EASTBOUND_TO_YARD]
    send(db, config, v.EASTBOUND_IN_YARD)  # nothing to wait for
    assert db.engines_at(v.AT_TRAIN, v.LOCAL) == []  # the local's engines are put away
    with pytest.raises(SignalRefused, match="^Local return job is already done.$"):
        send(db, config, v.LOCAL_RETURN_DONE)


def test_eastbound_cant_enter_the_yard_before_the_local_return_job(railroad):
    db, config = railroad
    to_the_local(db, config)
    send(db, config, v.LOCAL_BACK)  # the local brought back undelivered cars
    with pytest.raises(SignalRefused, match="^The eastbound can't enter the yard"):
        send(db, config, v.EASTBOUND_IN_YARD)
    with pytest.raises(SignalRefused, match="^Waiting on the Local return job.$"):
        send(db, config, v.SWITCH_EASTBOUND_DONE)
    send(db, config, v.LOCAL_RETURN_DONE)
    send(db, config, v.EASTBOUND_IN_YARD)


# --- whole days ------------------------------------------------------------------------


@pytest.mark.parametrize("skip_chance,mode", [(0.0, v.CHORE_FULL), (0.25, v.CHORE_FULL),
                                              (0.0, v.CHORE_QUICK), (0.25, v.CHORE_QUICK)])
def test_many_days_keep_the_railroad_consistent(railroad, skip_chance, mode):
    db, config = railroad
    set_chore_mode(db, mode)
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


# --- quick chores ----------------------------------------------------------------------


def test_arriving_train_keeps_its_order_and_spares_lose_theirs(railroad):
    db, config = railroad
    to_the_local(db, config)
    train = [c.id for c in db.cars_at(v.AT_TRAIN, v.WESTBOUND_MANIFEST)]
    send(db, config, v.WESTBOUND_IN_WEST_STAGING)
    placed = sorted((c for c in db.cars_at(v.AT_WORLD, v.WEST_STAGING) if c.seq is not None),
                    key=lambda c: c.seq)
    assert [c.id for c in placed] == train
    assert [c.seq for c in placed] == list(range(1, len(train) + 1))


def test_chore_toggle_takes_effect_at_the_next_day_advance(railroad):
    db, config = railroad
    assert set_chore_mode(db, "quick") == [
        "Chores will be quick from the next day advance on; today's chores stay as planned."]
    session = db.session()
    assert (session.west_chore_mode, session.east_chore_mode) == (v.CHORE_FULL, v.CHORE_FULL)
    with pytest.raises(SignalRefused, match="'Simple' is not a chore mode: Full or Quick."):
        set_chore_mode(db, "Simple")
    run_day(db, config, random.Random(1))
    session = db.session()
    assert (session.west_chore_mode, session.east_chore_mode) == (v.CHORE_QUICK, v.CHORE_QUICK)


def test_quick_chore_after_a_cold_start_is_a_full_one(tmp_path, samples_dir):
    data = yaml.safe_load((samples_dir / "config.yaml").read_text())
    data["settings"]["chore_mode"] = "Quick"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    config = load_config(path)
    db = Database.open(":memory:")
    cold_start(db, config, samples_dir / "cars.csv", samples_dir / "engines.csv",
               rng=random.Random(1))
    session = db.session()
    assert session.next_chore_mode == v.CHORE_QUICK
    assert (session.west_chore_mode, session.east_chore_mode) == (v.CHORE_FULL, v.CHORE_FULL)


@pytest.mark.parametrize("seed", range(6))
def test_quick_chores_reuse_yesterdays_trains(railroad, seed):
    db, config = railroad
    set_chore_mode(db, v.CHORE_QUICK)
    rng = random.Random(seed)
    for _ in range(3):
        run_day(db, config, rng)
        s = config.settings
        session = db.session()
        assert (session.west_chore_mode, session.east_chore_mode) == (
            v.CHORE_QUICK, v.CHORE_QUICK)

        # Westbound: the eastbound as it reached the East loop, Local block moved to the rear.
        loop = [c for c in db.cars_at(v.AT_WORLD, v.EAST_STAGING)]
        plan = [db.car(e.car_id) for e in db.consist_plan(v.WESTBOUND_MANIFEST) if e.car_id]
        block = [c for c in plan if c.assigned_spot]
        assert plan == [c for c in loop if not c.assigned_spot] + block

        # Eastbound: yesterday's westbound the other way round, changed only at the rear.
        before = west_train(db.cars())
        plan = [db.car(e.car_id) for e in db.consist_plan(v.EASTBOUND_MANIFEST) if e.car_id]
        reused = [c for c in plan if c in before and not c.assigned_spot]
        assert plan[:len(reused)] == reused  # reused cars first, in their order
        assert reused == [c for c in before if c in reused]
        assert all(c.assigned_spot for c in plan[len(plan) - sum(
            bool(c.assigned_spot) for c in plan):])  # Local block at the rear
        wanted = min(max(len(before), s.eastbound_length_min), s.eastbound_length_max)
        blocks = sum(bool(c.assigned_spot) for c in plan)
        assert wanted <= len(plan) <= max(wanted, blocks + len(config.spots))


def test_swap_rear_takes_cars_off_the_rear_and_keeps_east_supply():
    from trainops.db import Car
    from trainops.planning import _Planner
    def car(n, spot=None):
        return Car(id=n, mark="X", number=str(n), type="boxcar", loc_kind=v.AT_WORLD,
                   loc_ref=v.WEST_STAGING, seq=n, load=v.NOT_TRACKED,
                   last_loaded_industry=None, origin_world=v.WEST_STAGING,
                   assigned_spot=spot, dest_world=None, days_held=0, bad_order=False)
    train = [car(n) for n in range(1, 9)]  # head -> rear
    spares = [car(n) for n in range(20, 25)]
    planner = _Planner.__new__(_Planner)
    planner.rng = random.Random(1)
    planner.west_left = [c for c in train + spares]
    # Local block: one car from the middle of the train (3) and one spare (20);
    # East supply: one car near the rear (7, kept) and one spare (21, added).
    block, supply = [train[2], spares[0]], [train[6], spares[1]]
    planner.west_left = [c for c in planner.west_left if c not in block + supply]
    cars = planner._swap_rear(train, block, supply, length=8)
    # Same length (8): the rearmost cars not needed (8, then 6) come off; East-supply
    # car 7 stays; spare 21 goes on ahead of the Local block; 3 is sorted to the rear.
    assert [c.id for c in cars] == [1, 2, 4, 5, 7, 21, 3, 20]
    # Longer than yesterday: spares fill in ahead of the Local block.
    cars = planner._swap_rear(train, block, supply, length=12)
    ids = [c.id for c in cars]
    assert ids[:7] == [1, 2, 4, 5, 6, 7, 8] and ids[7] == 21 and ids[-2:] == [3, 20]
    assert len(ids) == 12 and set(ids[8:10]) <= {22, 23, 24}


def test_quick_chore_sheets(railroad):
    db, config = railroad
    from trainops.worklists import chore_sheet
    set_chore_mode(db, v.CHORE_QUICK)
    run_day(db, config, random.Random(4))
    west = chore_sheet(db, config, v.WEST_STAGING).splitlines()
    assert west[0] == "WEST STAGING — Eastbound manifest  (Quick chore)"
    assert [l.split(".")[0] for l in west[1:7]] == ["1", "2", "3", "4", "5", "6"]
    assert west[3].startswith("3. Cars off the train → spare tracks:")
    assert west[4].startswith("4. Cars from the spare tracks → train:")
    assert west[5].startswith("5. Cars moved to the rear of the train (Local block):")
    assert west[6] == "6. Train list"
    east = chore_sheet(db, config, v.EAST_STAGING).splitlines()
    assert east[0] == "EAST LOOP — Westbound manifest  (Quick chore)"
    assert east[3].startswith("3. Cars moved to the rear of the train (Local block):")
    assert east[4] == "4. Train list"
    # What comes off and goes on matches the plan.
    before = west_train(db.cars())
    plan = [db.car(e.car_id) for e in db.consist_plan(v.EASTBOUND_MANIFEST) if e.car_id]
    off = [c for c in before if c not in plan]
    on = [c for c in plan if c not in before]
    for car in off:
        assert car.label in west[3]
    for car in on:
        assert car.label in west[4]


def _like_for_like_swaps(db, config, rng, days):
    """Spares put on the eastbound while a car of their type came off (quick chores)."""
    set_chore_mode(db, v.CHORE_QUICK)
    swaps = 0
    for _ in range(days):
        run_day(db, config, rng)
        before = west_train(db.cars())  # yesterday's westbound, head -> rear as an eastbound
        plan = [db.car(e.car_id) for e in db.consist_plan(v.EASTBOUND_MANIFEST) if e.car_id]
        planned = {c.id for c in plan}
        in_train = {c.id for c in before}
        # A car last loaded at a shipper may not go back to it loaded, so it may be
        # passed over; only count cars that could serve anywhere.
        off = [c for c in before if c.id not in planned and c.last_loaded_industry is None]
        on = [c for c in plan if c.id not in in_train]
        swaps += sum(1 for c in on if any(o.type == c.type for o in off))
    return swaps


def test_quick_chores_use_cars_already_in_the_train(railroad, monkeypatch, samples_dir):
    db, config = railroad
    assert _like_for_like_swaps(db, config, random.Random(0), days=30) == 0
    # Choosing at random from all of West staging (as a full chore does) would swap.
    from trainops.planning import _Planner
    monkeypatch.setattr(_Planner, "_take_west",
                        lambda self, demand, rearmost: self._take_random(self.west_left, demand))
    db2 = Database.open(":memory:")
    cold_start(db2, config, samples_dir / "cars.csv", samples_dir / "engines.csv",
               rng=random.Random(5))  # the same start as the railroad
    assert _like_for_like_swaps(db2, config, random.Random(0), days=30) > 0
