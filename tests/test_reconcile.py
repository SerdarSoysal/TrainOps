"""Step 3: bringing saved spot states in line with a reloaded configuration."""

import copy

import pytest

from trainops import vocab as v
from trainops.config import load_config, parse_config
from trainops.db import Database, SpotState
from trainops.reconcile import reconcile_spot_states


@pytest.fixture
def db():
    database = Database.open(":memory:")
    yield database
    database.close()


@pytest.fixture
def sample(samples_dir):
    return load_config(samples_dir / "config.yaml")


def raw_sample(samples_dir):
    import yaml

    with open(samples_dir / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_spot(raw, spot_id):
    for industry in raw["industries"]:
        for spot in industry["spots"]:
            if spot["spot_id"] == spot_id:
                return industry, spot
    raise KeyError(spot_id)


def test_first_run_creates_a_state_for_every_spot(db, sample):
    with db.transaction():
        db.update_session(day=4)
    notes = reconcile_spot_states(db, sample)
    states = db.spot_states()
    assert set(states) == set(sample.spots_by_id)
    for state in states.values():
        assert state.state == v.AWAITING_CAR
        assert state.waiting_since_day == 4
    assert "Northfield Paper, Loading door 1: new spot, now awaiting a car." in notes
    assert len(notes) == 7


def test_second_run_changes_nothing(db, sample):
    reconcile_spot_states(db, sample)
    before = db.spot_states()
    assert reconcile_spot_states(db, sample) == []
    assert db.spot_states() == before


def test_reload_keeps_runtime_state(db, sample):
    reconcile_spot_states(db, sample)
    busy = SpotState(
        "northfield_door_1", v.READY_FOR_PICKUP, position=2, out_dest=v.WEST, next_delay=False
    )
    with db.transaction():
        db.put_spot_state(busy)
    assert reconcile_spot_states(db, sample) == []
    assert db.spot_state("northfield_door_1") == busy


def test_removed_spot_is_reported_and_its_state_kept(db, sample, samples_dir):
    reconcile_spot_states(db, sample)
    with db.transaction():
        db.add_car(
            mark="UTLX",
            number="98120",
            type="tank car",
            loc_kind=v.AT_SPOT,
            loc_ref="northfield_chemical",
            origin_world=v.EAST_STAGING,
        )
        db.add_car(
            mark="GATX",
            number="21044",
            type="tank car",
            loc_kind=v.AT_YARD,
            loc_ref=v.LOCALS_TRACK,
            seq=1,
            origin_world=v.EAST_STAGING,
            assigned_spot="northfield_chemical",
        )
    raw = raw_sample(samples_dir)
    industry, spot = find_spot(raw, "northfield_chemical")
    industry["spots"].remove(spot)

    notes = reconcile_spot_states(db, parse_config(raw))
    assert notes == [
        "The spot with id 'northfield_chemical' is no longer in the configuration. "
        "Its saved state is kept but ignored.",
        "  Car UTLX 98120 is still at that spot — move it with the edit tool.",
        "  Car GATX 21044 is assigned to that spot — fix it with the edit tool.",
    ]
    assert db.spot_state("northfield_chemical") is not None

    # Putting the spot back brings its old state back, with no new notes.
    assert reconcile_spot_states(db, sample) == []


def test_shorter_pattern_wraps_position(db, sample, samples_dir):
    reconcile_spot_states(db, sample)  # door 1 pattern: East, East, West
    with db.transaction():
        db.put_spot_state(SpotState("northfield_door_1", v.PROCESSING, days_left=1, position=2))
    raw = raw_sample(samples_dir)
    find_spot(raw, "northfield_door_1")[1]["pattern"] = ["East", "West"]

    notes = reconcile_spot_states(db, parse_config(raw))
    assert notes == [
        "Northfield Paper, Loading door 1: pattern is shorter now; position 3 wraps around to 1."
    ]
    state = db.spot_state("northfield_door_1")
    assert state.position == 0
    assert (state.state, state.days_left) == (v.PROCESSING, 1)


def test_random_spot_whose_requirement_was_removed_is_reset(db, sample, samples_dir):
    reconcile_spot_states(db, sample)  # team track 2 has 3 possible requirements
    with db.transaction():
        db.put_spot_state(
            SpotState(
                "transfer_track_2",
                v.PROCESSING,
                days_left=2,
                requirement_number=3,
                requirement_side=v.EAST,
                next_requirement_number=1,
                next_requirement_side=v.WEST,
            )
        )
        db.add_car(
            mark="UTLX",
            number="98120",
            type="tank car",
            loc_kind=v.AT_SPOT,
            loc_ref="transfer_track_2",
            origin_world=v.EAST_STAGING,
        )
        db.update_session(day=9)
    raw = raw_sample(samples_dir)
    find_spot(raw, "transfer_track_2")[1]["possible_requirements"].pop()  # drop number 3

    notes = reconcile_spot_states(db, parse_config(raw))
    assert notes == [
        "Transfer Facility, Team track 2: its current requirement is no longer in the "
        "configuration; the spot is reset to awaiting a car and will draw a new one.",
        "  Car UTLX 98120 is still at that spot — move it with the edit tool.",
    ]
    state = db.spot_state("transfer_track_2")
    assert state.state == v.AWAITING_CAR
    assert state.requirement_number is None
    assert state.waiting_since_day == 9
    # The day-ahead draw (number 1) still exists, so it is kept.
    assert (state.next_requirement_number, state.next_requirement_side) == (1, v.WEST)


def test_day_ahead_draw_that_no_longer_exists_is_cleared_quietly(db, sample, samples_dir):
    reconcile_spot_states(db, sample)
    with db.transaction():
        db.put_spot_state(
            SpotState(
                "transfer_track_2",
                v.AWAITING_CAR,
                requirement_number=1,
                requirement_side=v.WEST,
                next_requirement_number=3,
                next_requirement_side=v.EAST,
            )
        )
    raw = raw_sample(samples_dir)
    find_spot(raw, "transfer_track_2")[1]["possible_requirements"].pop()

    assert reconcile_spot_states(db, parse_config(raw)) == []
    state = db.spot_state("transfer_track_2")
    assert state.requirement_number == 1
    assert state.next_requirement_number is None and state.next_requirement_side is None


def test_fixed_spot_that_became_random_mid_cycle_is_reset(db, sample, samples_dir):
    reconcile_spot_states(db, sample)
    with db.transaction():
        db.put_spot_state(SpotState("harbor_pit", v.PROCESSING, days_left=1))
    raw = raw_sample(samples_dir)
    _, pit = find_spot(raw, "harbor_pit")
    requirement = {
        k: pit.pop(k)
        for k in ("car_type", "direction", "base_processing_days", "delay_chance", "cooldown_days")
    }
    pit.pop("source")
    requirement["source_weights"] = {"West": 1}
    pit.update(requirement_mode="random", possible_requirements=[requirement])

    notes = reconcile_spot_states(db, parse_config(raw))
    assert "the spot is reset to awaiting a car" in notes[0]
    assert db.spot_state("harbor_pit").state == v.AWAITING_CAR


def test_random_spot_that_became_fixed_drops_its_draws(db, sample, samples_dir):
    reconcile_spot_states(db, sample)
    with db.transaction():
        db.put_spot_state(
            SpotState(
                "transfer_track_2",
                v.PROCESSING,
                days_left=1,
                requirement_number=1,
                requirement_side=v.EAST,
                next_requirement_number=2,
                next_requirement_side=v.WEST,
            )
        )
    raw = raw_sample(samples_dir)
    _, track = find_spot(raw, "transfer_track_2")
    track.pop("possible_requirements")
    track.update(
        requirement_mode="fixed",
        car_type="boxcar",
        direction="incoming",
        source="East",
        base_processing_days=2,
    )

    notes = reconcile_spot_states(db, parse_config(raw))
    assert notes == [
        "Transfer Facility, Team track 2: now a fixed spot; it follows its fixed requirement."
    ]
    state = db.spot_state("transfer_track_2")
    assert (state.state, state.days_left) == (v.PROCESSING, 1)
    assert state.requirement_number is None and state.next_requirement_number is None


def test_new_spot_in_reloaded_config_starts_fresh(db, sample, samples_dir):
    reconcile_spot_states(db, sample)
    raw = raw_sample(samples_dir)
    industry, spot = find_spot(raw, "harbor_pit")
    extra = copy.deepcopy(spot)
    extra.update(spot_id="harbor_pit_2", name="Unloading pit 2")
    industry["spots"].append(extra)

    notes = reconcile_spot_states(db, parse_config(raw))
    assert notes == ["Harbor Feed Mill, Unloading pit 2: new spot, now awaiting a car."]
    assert db.spot_state("harbor_pit_2").state == v.AWAITING_CAR
