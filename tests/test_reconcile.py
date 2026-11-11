"""Spot states versus the configuration: created at cold start, checked at start-up."""

import copy
from dataclasses import replace

import pytest
import yaml

from trainops import vocab as v
from trainops.config import load_config, parse_config
from trainops.db import Database
from trainops.reconcile import (
    ColdStartNeeded,
    check_config,
    create_spot_states,
    spot_identity,
)


@pytest.fixture
def db():
    database = Database.open(":memory:")
    yield database
    database.close()


@pytest.fixture
def sample(samples_dir):
    return load_config(samples_dir / "config.yaml")


@pytest.fixture
def raw(samples_dir):
    """The sample configuration as plain data, to change in a test."""
    with open(samples_dir / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def started(db, sample):
    """A database after a cold start with the sample configuration."""
    with db.transaction():
        db.update_session(day=4)
        create_spot_states(db, sample)
    return db


def find_spot(raw, spot_id):
    for industry in raw["industries"]:
        for spot in industry["spots"]:
            if spot["spot_id"] == spot_id:
                return industry, spot
    raise KeyError(spot_id)


def reasons_for(db, raw):
    with pytest.raises(ColdStartNeeded) as info:
        check_config(db, parse_config(raw))
    return info.value.reasons


# --- creating at cold start ---------------------------------------------------------


def test_cold_start_creates_a_waiting_state_for_every_spot(started, sample):
    states = started.spot_states()
    assert set(states) == set(sample.spots_by_id)
    for state in states.values():
        assert state.state == v.AWAITING_CAR
        assert state.waiting_since_day == 4
    assert states["harbor_pit"].industry_id == "harbor_feed"


def test_spot_identity_in_plain_words(sample):
    assert spot_identity(sample.spot("northfield_door_1")) == "Fixed: boxcar, Outgoing"
    assert spot_identity(sample.spot("transfer_track_2")) == (
        "Random: boxcar, Incoming; covered hopper, Outgoing; tank car, Incoming"
    )


# --- start-up check: nothing changed -----------------------------------------------------


def test_no_cold_start_yet(db, sample):
    with pytest.raises(ColdStartNeeded) as info:
        check_config(db, sample)
    assert info.value.reasons == ["no cold start has been done yet."]


def test_unchanged_config_passes_and_keeps_state(started, sample):
    before = started.spot_states()
    assert check_config(started, sample) == []
    assert started.spot_states() == before


# --- changes that take effect without a cold start ------------------------------------------


def test_tuning_changes_need_no_cold_start(started, raw):
    raw["settings"]["delay_chance_max"] = 0.5
    raw["industries"][0]["name"] = "Northfield Paper Company"
    _, door = find_spot(raw, "northfield_door_1")
    door.update(
        name="Door 1",
        base_processing_days=4,
        delay_chance=0.3,
        disruption_chance=0,
        idle_days=2,
        pattern=["West", "East", "West", "East"],
        car_type="BOXCAR",  # capitals don't matter
    )
    _, track = find_spot(raw, "transfer_track_2")
    track["possible_requirements"][0].update(
        weight=10, source_weights={"East": 1}, base_processing_days=5
    )
    assert check_config(started, parse_config(raw)) == []


def test_shorter_pattern_wraps_position(started, raw):
    state = started.spot_state("northfield_door_1")  # pattern: East, East, West
    with started.transaction():
        started.put_spot_state(replace(state, state=v.PROCESSING, days_left=1, position=2))
    find_spot(raw, "northfield_door_1")[1]["pattern"] = ["East", "West"]

    notes = check_config(started, parse_config(raw))
    assert notes == [
        "Northfield Paper, Loading door 1: pattern is shorter now; position 3 wraps around to 1."
    ]
    state = started.spot_state("northfield_door_1")
    assert state.position == 0
    assert (state.state, state.days_left) == (v.PROCESSING, 1)


# --- changes that need a cold start -------------------------------------------------------


def test_new_spot_needs_cold_start(started, raw):
    industry, pit = find_spot(raw, "harbor_pit")
    extra = copy.deepcopy(pit)
    extra.update(spot_id="harbor_pit_2", name="Unloading pit 2")
    industry["spots"].append(extra)
    assert reasons_for(started, raw) == ["Harbor Feed Mill, Unloading pit 2 is new."]


def test_removed_spot_needs_cold_start(started, raw):
    industry, spot = find_spot(raw, "northfield_chemical")
    industry["spots"].remove(spot)
    assert reasons_for(started, raw) == ["the spot with id 'northfield_chemical' was removed."]


def test_removed_industry_needs_cold_start(started, raw):
    raw["industries"] = [i for i in raw["industries"] if i["id"] != "harbor_feed"]
    assert reasons_for(started, raw) == [
        "the spot with id 'harbor_dock' was removed.",
        "the spot with id 'harbor_pit' was removed.",
    ]


def test_changed_industry_id_needs_cold_start(started, raw):
    raw["industries"][1]["id"] = "harbor_mill"
    assert reasons_for(started, raw) == [
        "Harbor Feed Mill, Unloading pit: its industry id changed from 'harbor_feed' to "
        "'harbor_mill'.",
        "Harbor Feed Mill, Bagged feed dock: its industry id changed from 'harbor_feed' to "
        "'harbor_mill'.",
    ]


def test_changed_car_type_needs_cold_start(started, raw):
    find_spot(raw, "harbor_pit")[1]["car_type"] = "tank car"
    assert reasons_for(started, raw) == [
        "Harbor Feed Mill, Unloading pit changed from 'Fixed: covered hopper, Incoming' "
        "to 'Fixed: tank car, Incoming'."
    ]


def test_changed_direction_needs_cold_start(started, raw):
    _, pit = find_spot(raw, "harbor_pit")
    pit.pop("source")
    pit.update(direction="outgoing", pattern=["East"])
    assert "changed from 'Fixed: covered hopper, Incoming'" in reasons_for(started, raw)[0]


def test_changed_mode_needs_cold_start(started, raw):
    _, pit = find_spot(raw, "harbor_pit")
    requirement = {
        k: pit.pop(k)
        for k in ("car_type", "direction", "base_processing_days", "delay_chance", "idle_days")
    }
    pit.pop("source")
    requirement["source_weights"] = {"West": 1}
    pit.update(requirement_mode="random", possible_requirements=[requirement])
    assert reasons_for(started, raw) == [
        "Harbor Feed Mill, Unloading pit changed from 'Fixed: covered hopper, Incoming' "
        "to 'Random: covered hopper, Incoming'."
    ]


def test_changed_random_requirement_list_needs_cold_start(started, raw):
    find_spot(raw, "transfer_track_2")[1]["possible_requirements"].pop()
    (reason,) = reasons_for(started, raw)
    assert reason.startswith("Transfer Facility, Team track 2 changed from")


def test_every_reason_is_listed_at_once(started, raw):
    find_spot(raw, "harbor_pit")[1]["car_type"] = "tank car"
    industry, spot = find_spot(raw, "northfield_chemical")
    industry["spots"].remove(spot)
    with pytest.raises(ColdStartNeeded) as info:
        check_config(started, parse_config(raw))
    assert len(info.value.reasons) == 2
    assert str(info.value).startswith("A cold start is needed before the program can run:")
