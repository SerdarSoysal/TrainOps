"""Step 1: the package imports and the sample files load.

These are sanity checks on the sample data only. Full config checking
is step 2; CSV import checking is step 4.
"""

import csv
from collections import Counter

import yaml

import trainops


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_config(samples_dir):
    with open(samples_dir / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def all_spots(config):
    return [spot for ind in config["industries"] for spot in ind["spots"]]


# --- package -----------------------------------------------------------

def test_package_imports():
    assert trainops.__version__


# --- config.yaml -------------------------------------------------------

def test_config_loads_with_default_settings(samples_dir):
    settings = load_config(samples_dir)["settings"]
    assert settings == {
        "hold_days_on_locals": 2,
        "eastbound_length_min": 12,
        "eastbound_length_max": 20,
        "train_nominal_max": 20,
        "three_engines_from": 16,
        "capacity": {"east_staging": 30, "west_staging": 70, "yard_track": 35},
    }


def test_config_has_made_up_industries(samples_dir):
    industries = load_config(samples_dir)["industries"]
    assert 2 <= len(industries) <= 3
    for ind in industries:
        assert ind["id"] and ind["name"] and ind["spots"]


def test_spot_ids_are_unique(samples_dir):
    ids = [s["spot_id"] for s in all_spots(load_config(samples_dir))]
    assert len(ids) == len(set(ids))


def test_sample_covers_every_spot_kind(samples_dir):
    """The sample must exercise fixed incoming, fixed outgoing and random spots."""
    spots = all_spots(load_config(samples_dir))
    kinds = {
        (s["requirement_mode"], s.get("direction")) for s in spots
    }
    assert ("fixed", "incoming") in kinds
    assert ("fixed", "outgoing") in kinds
    assert any(mode == "random" for mode, _ in kinds)


def test_config_uses_plain_language_directions(samples_dir):
    for spot in all_spots(load_config(samples_dir)):
        assert "position" not in spot  # runtime state, lives in the database
        if spot["requirement_mode"] == "fixed":
            assert spot["direction"] in ("incoming", "outgoing")
            if spot["direction"] == "incoming":
                assert spot["source"] in ("East", "West")
            else:
                assert set(spot["pattern"]) <= {"East", "West"}
        else:
            for req in spot["possible_requirements"]:
                weights = req.get("source_weights") or req["destination_weights"]
                assert set(weights) <= {"East", "West"}


# --- cars.csv ----------------------------------------------------------

def test_cars_csv_loads(samples_dir):
    rows = load_csv(samples_dir / "cars.csv")
    assert rows
    assert list(rows[0].keys()) == ["mark", "number", "type", "location"]
    for row in rows:
        assert all(row[col] for col in ("mark", "number", "type", "location"))
        assert row["location"] in ("East staging", "West staging")


def test_cars_are_unique_by_mark_and_number(samples_dir):
    rows = load_csv(samples_dir / "cars.csv")
    keys = Counter((r["mark"], r["number"]) for r in rows)
    assert max(keys.values()) == 1


def test_cars_fit_staging_capacity(samples_dir):
    capacity = load_config(samples_dir)["settings"]["capacity"]
    per_world = Counter(r["location"] for r in load_csv(samples_dir / "cars.csv"))
    assert per_world["East staging"] <= capacity["east_staging"]
    assert per_world["West staging"] <= capacity["west_staging"]


def test_every_spot_car_type_exists_in_roster(samples_dir):
    roster_types = {r["type"] for r in load_csv(samples_dir / "cars.csv")}
    for spot in all_spots(load_config(samples_dir)):
        if spot["requirement_mode"] == "fixed":
            assert spot["car_type"] in roster_types, spot["name"]
        else:
            for req in spot["possible_requirements"]:
                assert req["car_type"] in roster_types, spot["name"]


# --- engines.csv -------------------------------------------------------

def test_engines_csv_loads(samples_dir):
    rows = load_csv(samples_dir / "engines.csv")
    assert list(rows[0].keys()) == ["mark", "number", "model", "pool", "location"]
    for row in rows:
        assert all(row[col] for col in ("mark", "number", "pool", "location"))
        assert row["pool"] in ("local", "switcher", "manifest")
        assert row["location"] in ("Storage", "East staging", "West staging")


def test_engine_pools_match_spec(samples_dir):
    pools = Counter(r["pool"] for r in load_csv(samples_dir / "engines.csv"))
    assert pools["switcher"] == 1
    assert pools["local"] >= 2
    assert pools["manifest"] >= 6  # enough for both manifests at 3 engines each


def test_engines_are_unique_by_mark_and_number(samples_dir):
    rows = load_csv(samples_dir / "engines.csv")
    keys = Counter((r["mark"], r["number"]) for r in rows)
    assert max(keys.values()) == 1
