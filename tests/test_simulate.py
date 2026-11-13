"""Step 10: the simulator and the command line."""

import random

import pytest

from trainops import vocab as v
from trainops.cli import main, play_loop
from trainops.coldstart import cold_start
from trainops.config import load_config
from trainops.db import Database
from trainops.simulate import InvariantBroken, _Sim, format_report, simulate
from trainops.worklists import actions


@pytest.fixture
def config(samples_dir):
    return load_config(samples_dir / "config.yaml")


@pytest.fixture
def roster(samples_dir):
    return samples_dir / "cars.csv", samples_dir / "engines.csv"


# --- the simulator ---------------------------------------------------------------------


def test_simulation_keeps_every_rule(config, roster):
    report = simulate(config, *roster, days=40, seed=4, skip_chance=0.2, bad_order_chance=0.2)
    assert report.broken is None
    assert report.days == 40
    assert report.never_served == []
    assert len(report.westbound_lengths) == len(report.eastbound_lengths) == 40
    assert all(12 <= n <= 20 for n in report.eastbound_leaving_west)
    assert report.skipped_moves > 0 and report.bad_orders > 0
    assert sum(report.setouts.values()) > 40


def test_same_seed_same_run(config, roster):
    a = simulate(config, *roster, days=15, seed=9, skip_chance=0.1)
    b = simulate(config, *roster, days=15, seed=9, skip_chance=0.1)
    assert format_report(a, config) == format_report(b, config)


def test_report_reads_plainly(config, roster):
    text = format_report(simulate(config, *roster, days=10, seed=2), config)
    assert text.startswith("TrainOps simulation: 10 days, seed 2")
    assert "Every check held after all" in text
    assert "Westbound manifest: shortest" in text
    for spot in config.spots:
        assert spot.label in text
    assert "Yard tracks, most cars at once (capacity 35)" in text


def test_a_broken_rule_is_caught(config, roster):
    db = Database.open(":memory:")
    sim = _Sim(db, config, seed=1, skip_chance=0, bad_order_chance=0)
    cold_start(db, config, *roster, rng=random.Random(1))
    sim.car_ids = {c.id for c in db.cars()}
    sim._check()
    with db.transaction():
        car = db.cars_at(v.AT_WORLD, v.WEST_STAGING)[0]
        db.update_car(car.id, loc_kind=v.AT_SPOT, loc_ref="harbor_pit")  # spot is awaiting
    with pytest.raises(InvariantBroken, match="Unloading pit is awaiting car with 1 cars"):
        sim._check()
    with db.transaction():
        db.remove_car(car.id)
    with pytest.raises(InvariantBroken, match="disappeared"):
        sim._check()


# --- the buttons -----------------------------------------------------------------------


def test_buttons_follow_the_current_job(config, roster):
    db = Database.open(":memory:")
    cold_start(db, config, *roster, rng=random.Random(3))
    labels = [a.label for a in actions(db, config)]
    assert labels == [v.WEST_CHORE_DONE, v.EAST_CHORE_DONE]
    from trainops.signals import handle
    handle(db, config, v.WEST_CHORE_DONE)
    assert [a.label for a in actions(db, config)] == [v.EAST_CHORE_DONE]
    handle(db, config, v.EAST_CHORE_DONE)
    # The eastbound's button waits for the Local return job.
    assert [a.signal for a in actions(db, config)] == [v.WESTBOUND_IN_YARD]
    handle(db, config, v.WESTBOUND_IN_YARD)
    assert [a.signal for a in actions(db, config)] == [v.SWITCH_WESTBOUND_DONE]
    handle(db, config, v.SWITCH_WESTBOUND_DONE)
    buttons = actions(db, config)
    assert buttons[0].signal == v.WESTBOUND_IN_WEST_STAGING  # open alongside the local
    local = buttons[1:]
    assert local[-1].signal == v.LOCAL_BACK
    for act in local[:-1]:
        assert act.signal == v.SET_OUT_DONE  # day 1: nothing to pull yet
        assert act.label.startswith("Spot ") and config.spot(act.spot_id).label in act.label


# --- the command line ------------------------------------------------------------------


def test_simulate_command(capsys, samples_dir):
    code = main(["simulate", "--days", "5", "--config", str(samples_dir / "config.yaml"),
                 "--cars", str(samples_dir / "cars.csv"),
                 "--engines", str(samples_dir / "engines.csv")])
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("TrainOps simulation: 5 days, seed 1")


def test_play_needs_a_cold_start_first(capsys, tmp_path, samples_dir):
    code = main(["play", "--db", str(tmp_path / "state.db"),
                 "--config", str(samples_dir / "config.yaml")])
    assert code == 1
    out = capsys.readouterr().out
    assert "A cold start is needed" in out
    assert "--cold-start" in out


def test_play_runs_a_whole_day_by_number(config, roster):
    db = Database.open(":memory:")
    cold_start(db, config, *roster, rng=random.Random(3))
    typed = []

    def read(prompt):
        # Always press the first button; stop once day 2 has begun.
        if db.session().day == 2:
            return "q"
        typed.append("1")
        return "1"

    shown = []
    play_loop(db, config, read, shown.append, rng=random.Random(1))
    text = "\n".join(shown)
    assert db.session().day == 2
    assert "=== Day 1 — Pre-session chores ===" in text
    assert "Day 2 begins." in text
    assert "Refused" not in text


def test_play_other_commands(config, roster):
    db = Database.open(":memory:")
    cold_start(db, config, *roster, rng=random.Random(3))
    answers = iter(["s", "l", "what", "99", "q"])
    shown = []
    play_loop(db, config, lambda prompt: next(answers), shown.append)
    text = "\n".join(shown)
    assert "Harbor Feed Mill, Unloading pit: Awaiting car" in text  # s
    assert "LOCAL RETURN JOB" in text  # l shows every list
    assert text.count("Type a number to send that signal") >= 3  # help after bad input


@pytest.mark.parametrize("mode", ["Quick", "Mixed"])
def test_quick_chores_keep_every_rule(config, roster, mode):
    report = simulate(config, *roster, days=40, seed=2, skip_chance=0.2,
                      bad_order_chance=0.1, chore_mode=mode)
    assert report.broken is None
    assert report.never_served == []
    assert report.quick_chores[v.WEST_STAGING] > 0 and report.quick_chores[v.EAST_STAGING] > 0
    if mode == "Quick":  # every day but day 1 (no train order known after a cold start)
        assert report.quick_chores[v.WEST_STAGING] == 39


def test_play_changes_the_chore_mode(config, roster):
    db = Database.open(":memory:")
    cold_start(db, config, *roster, rng=random.Random(3))
    answers = iter(["c", "q"])
    shown = []
    play_loop(db, config, lambda prompt: next(answers), shown.append)
    text = "\n".join(shown)
    assert "Chores: full today; full from the next day advance (c = change)" in text
    assert "Chores will be quick from the next day advance on" in text
    assert db.session().next_chore_mode == v.CHORE_QUICK
    assert db.session().west_chore_mode == v.CHORE_FULL  # today's chores stay as planned
