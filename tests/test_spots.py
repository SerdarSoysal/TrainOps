"""Step 5: spot logic."""

import random
from collections import Counter
from dataclasses import replace

import pytest

from trainops import vocab as v
from trainops.config import parse_config
from trainops.db import SpotState
from trainops.spots import (
    Need,
    SpotRuleError,
    advance,
    need,
    pull,
    roll_ahead,
    set_out,
    upcoming_need,
)


def make_config(*spots, **settings):
    return parse_config(
        {"settings": settings, "industries": [{"id": "mill", "name": "Mill", "spots": list(spots)}]}
    )


def fixed_out(**changes):
    spot = {
        "spot_id": "door",
        "name": "Door",
        "requirement_mode": "fixed",
        "car_type": "boxcar",
        "direction": "outgoing",
        "pattern": ["East", "East", "West"],
        "base_processing_days": 2,
    }
    spot.update(changes)
    return spot


def fixed_in(**changes):
    spot = {
        "spot_id": "pit",
        "name": "Pit",
        "requirement_mode": "fixed",
        "car_type": "covered hopper",
        "direction": "incoming",
        "source": "West",
        "base_processing_days": 1,
    }
    spot.update(changes)
    return spot


def random_spot(*requirements):
    return {
        "spot_id": "team",
        "name": "Team track",
        "requirement_mode": "random",
        "possible_requirements": list(requirements)
        or [
            {
                "car_type": "boxcar",
                "direction": "incoming",
                "source_weights": {"East": 1},
                "base_processing_days": 1,
                "idle_days": 0,
            },
            {
                "car_type": "tank car",
                "direction": "outgoing",
                "destination_weights": {"West": 1},
                "base_processing_days": 2,
                "idle_days": 2,
            },
        ],
    }


def fresh(spot_id, day=1):
    return SpotState.fresh(spot_id, day, industry_id="mill", identity="test")


class Run:
    """One spot driven through days, with a seeded random generator."""

    def __init__(self, spot_dict, seed=1, **settings):
        self.config = make_config(spot_dict, **settings)
        self.spot = self.config.spots[0]
        self.rng = random.Random(seed)
        self.day = 1
        self.state = roll_ahead(self.spot, fresh(self.spot.spot_id), self.rng, self.config.settings)

    def advance(self, *, delay=None, frozen=False):
        if delay is not None:  # force the day-early delay roll
            self.state = replace(self.state, next_delay=delay)
        self.day += 1
        self.state = advance(
            self.spot, self.state, self.rng, self.config.settings, self.day, frozen=frozen
        )
        return self.state

    def set_out(self):
        self.state = set_out(self.spot, self.state)
        return self.state

    def pull(self, **kw):
        self.state = pull(self.spot, self.state, self.day, **kw)
        return self.state


# --- what a spot needs -----------------------------------------------------------------


def test_fixed_incoming_need():
    run = Run(fixed_in(idle_days=1, delay_chance=0.2))
    assert need(run.spot, run.state) == Need("covered hopper", v.INCOMING, v.WEST, 1, 0.2, 1)


def test_fixed_outgoing_need_follows_the_pattern_position():
    run = Run(fixed_out())
    assert need(run.spot, run.state).side == v.EAST
    assert need(run.spot, replace(run.state, position=2)).side == v.WEST


def test_cold_start_draws_a_random_spots_first_requirement_and_the_next_one():
    run = Run(random_spot())
    assert run.state.state == v.AWAITING_CAR
    assert run.state.requirement_number in (1, 2)
    assert run.state.next_requirement_number in (1, 2)
    current = need(run.spot, run.state)
    assert (current.car_type, current.side) in (("boxcar", v.EAST), ("tank car", v.WEST))


def test_every_spot_gets_a_day_early_delay_roll():
    run = Run(fixed_in())
    assert run.state.next_delay is False  # delay_chance 0


# --- the cycle ---------------------------------------------------------------------------


def test_set_out_starts_processing():
    run = Run(fixed_out())
    assert run.set_out().state == v.PROCESSING
    assert run.state.days_left == 2


def test_processing_counts_down_to_ready():
    run = Run(fixed_out())
    run.set_out()
    assert run.advance().state == v.PROCESSING
    assert run.state.days_left == 1
    assert run.advance().state == v.READY_FOR_PICKUP
    assert run.state.days_left is None


def test_one_processing_day_is_ready_the_next_day():
    run = Run(fixed_in())  # base 1
    run.set_out()
    assert run.advance().state == v.READY_FOR_PICKUP


def test_a_delay_holds_the_countdown_for_a_day():
    run = Run(fixed_in())
    run.set_out()
    assert run.advance(delay=True).state == v.PROCESSING
    assert run.state.days_left == 1
    assert run.advance(delay=False).state == v.READY_FOR_PICKUP


def test_delays_stack_without_limit():
    run = Run(fixed_in())
    run.set_out()
    for _ in range(10):
        assert run.advance(delay=True).state == v.PROCESSING
    assert run.advance(delay=False).state == v.READY_FOR_PICKUP


def test_pull_with_idle_days_goes_idle_then_awaiting():
    run = Run(fixed_in(idle_days=2))
    run.set_out()
    run.advance()
    assert run.pull().state == v.IDLE
    assert run.state.days_left == 2
    assert run.advance().state == v.IDLE
    assert run.advance().state == v.AWAITING_CAR
    assert run.state.waiting_since_day == run.day


def test_pull_with_no_idle_days_is_awaiting_at_once():
    run = Run(fixed_in(idle_days=0))
    run.set_out()
    run.advance()
    run.advance()  # sits ready a day (pull skipped)
    assert run.pull().state == v.AWAITING_CAR
    assert run.state.waiting_since_day == run.day


def test_awaiting_and_ready_spots_wait_indefinitely():
    run = Run(fixed_in())
    for _ in range(5):
        assert run.advance().state == v.AWAITING_CAR
    run.set_out()
    run.advance()
    for _ in range(5):
        assert run.advance().state == v.READY_FOR_PICKUP


# --- refusals ------------------------------------------------------------------------------


def test_set_out_only_when_awaiting():
    run = Run(fixed_out())
    run.set_out()
    with pytest.raises(SpotRuleError) as info:
        run.set_out()
    assert str(info.value) == (
        "Mill, Door is processing — a car can only be set out there when it is awaiting a car."
    )


def test_pull_only_when_ready():
    run = Run(fixed_out())
    with pytest.raises(SpotRuleError, match="Mill, Door is awaiting car — a car can only be pulled"):
        run.pull()


# --- outgoing destinations and the pattern ---------------------------------------------------


def complete_once(run):
    run.set_out()
    while run.advance(delay=False).state != v.READY_FOR_PICKUP:
        pass
    dest = run.state.out_dest
    run.pull()
    return dest


def test_destinations_follow_the_pattern_and_wrap():
    run = Run(fixed_out())  # East, East, West
    dests = [complete_once(run) for _ in range(7)]
    assert dests == ["East", "East", "West", "East", "East", "West", "East"]
    assert run.state.position == 1


def test_disruption_flips_one_result_but_position_still_advances():
    run = Run(fixed_out(disruption_chance=1))
    dests = [complete_once(run) for _ in range(3)]
    assert dests == ["West", "West", "East"]  # every one flipped
    assert run.state.position == 0


def test_disruptions_happen_at_about_their_chance():
    run = Run(fixed_out(pattern=["East"], disruption_chance=0.2), seed=7)
    dests = Counter(complete_once(run) for _ in range(2000))
    assert 0.17 < dests["West"] / 2000 < 0.23


def test_incoming_spot_has_no_destination():
    run = Run(fixed_in())
    run.set_out()
    run.advance()
    assert run.state.out_dest is None


def test_destination_is_kept_while_the_pull_is_late():
    run = Run(fixed_out(disruption_chance=0.5), seed=3)
    run.set_out()
    run.advance()
    run.advance()
    dest = run.state.out_dest
    for _ in range(4):
        assert run.advance().out_dest == dest


# --- random spots ------------------------------------------------------------------------


def test_random_outgoing_destination_is_the_side_drawn():
    run = Run(random_spot())
    run.state = replace(run.state, requirement_number=2, requirement_side=v.WEST)
    run.set_out()
    run.advance(delay=False)
    assert run.advance(delay=False).state == v.READY_FOR_PICKUP
    assert run.state.out_dest == v.WEST


def test_random_spot_takes_the_day_early_draw_when_awaiting_again():
    run = Run(random_spot())
    run.state = replace(
        run.state,
        requirement_number=1,
        requirement_side=v.EAST,
        next_requirement_number=2,
        next_requirement_side=v.WEST,
    )
    run.set_out()
    run.advance()
    assert upcoming_need(run.spot, run.state).car_type == "tank car"  # known a day early
    run.pull()  # requirement 1 has no idle days
    assert (run.state.requirement_number, run.state.requirement_side) == (2, v.WEST)
    assert run.state.next_requirement_number is None
    run.advance()  # the next draw is made at the day advance
    assert run.state.next_requirement_number in (1, 2)


def test_random_spot_after_idle_takes_its_draw_at_the_day_advance():
    run = Run(random_spot())
    run.state = replace(
        run.state,
        requirement_number=2,
        requirement_side=v.WEST,
        next_requirement_number=1,
        next_requirement_side=v.EAST,
    )
    run.set_out()
    run.advance(delay=False)
    run.advance(delay=False)
    run.pull()  # requirement 2 idles 2 days
    run.advance()
    assert run.state.state == v.IDLE
    run.advance()
    assert run.state.state == v.AWAITING_CAR
    assert (run.state.requirement_number, run.state.requirement_side) == (1, v.EAST)
    assert run.state.next_requirement_number is not None


def test_random_draws_follow_the_weights():
    spot = random_spot(
        {
            "car_type": "boxcar",
            "direction": "incoming",
            "source_weights": {"East": 0.25, "West": 0.75},
            "weight": 3,
            "base_processing_days": 1,
        },
        {
            "car_type": "tank car",
            "direction": "incoming",
            "source_weights": {"East": 1},
            "weight": 1,
            "base_processing_days": 1,
        },
    )
    run = Run(spot, seed=11)
    draws = Counter()
    for _ in range(4000):
        run.state = replace(run.state, next_requirement_number=None)
        run.state = roll_ahead(run.spot, run.state, run.rng, run.config.settings)
        draws[(run.state.next_requirement_number, run.state.next_requirement_side)] += 1
    assert 0.17 < draws[(1, v.EAST)] / 4000 < 0.21  # 3/4 * 1/4
    assert 0.54 < draws[(1, v.WEST)] / 4000 < 0.58  # 3/4 * 3/4
    assert 0.23 < draws[(2, v.EAST)] / 4000 < 0.27  # 1/4
    assert draws[(2, v.WEST)] == 0  # weight 0


# --- delay chances ------------------------------------------------------------------------


def delay_rate(spot_dict, samples=3000, **settings):
    run = Run(spot_dict, seed=5, **settings)
    run.set_out()
    hits = 0
    for _ in range(samples):
        hits += roll_ahead(run.spot, run.state, run.rng, run.config.settings).next_delay
    return hits / samples


def test_delays_happen_at_about_their_chance():
    assert 0.27 < delay_rate(fixed_in(delay_chance=0.3)) < 0.33


def test_delay_chance_max_caps_every_spot():
    assert 0.08 < delay_rate(fixed_in(delay_chance=0.9), delay_chance_max=0.1) < 0.12


def test_delay_chance_max_of_zero_means_no_delays():
    assert delay_rate(fixed_in(delay_chance=0.9), delay_chance_max=0) == 0


def test_cap_above_the_spots_chance_changes_nothing():
    assert 0.27 < delay_rate(fixed_in(delay_chance=0.3), delay_chance_max=0.8) < 0.33


# --- applied to the actual state ------------------------------------------------------------


def test_skipped_set_out_shifts_the_timeline_a_day():
    run = Run(fixed_in())
    run.advance(delay=True)  # the delay roll lands on a day nothing is processing
    assert run.state.state == v.AWAITING_CAR
    run.set_out()  # a day late
    assert run.advance(delay=False).state == v.READY_FOR_PICKUP


def test_skipped_pull_keeps_the_spot_ready():
    run = Run(fixed_out())
    run.set_out()
    run.advance(delay=False)
    run.advance(delay=False)
    position = run.state.position
    run.advance()
    run.advance()
    assert run.state.state == v.READY_FOR_PICKUP
    assert run.state.position == position  # no extra pattern steps


# --- bad order cars ------------------------------------------------------------------------


def test_a_bad_order_car_freezes_the_spot():
    run = Run(fixed_out())
    run.set_out()
    for _ in range(5):
        assert run.advance(delay=False, frozen=True).state == v.PROCESSING
    assert run.state.days_left == 2


def test_bad_order_pull_puts_the_spot_back_in_line():
    run = Run(fixed_out())
    run.advance()
    run.advance()
    waiting_since = run.state.waiting_since_day
    run.set_out()
    run.advance(delay=False, frozen=True)
    run.pull(bad_order=True)
    assert run.state.state == v.AWAITING_CAR
    assert run.state.waiting_since_day == waiting_since  # original place in line
    assert run.state.position == 0  # pattern not advanced: the work was never done
    assert need(run.spot, run.state).side == v.EAST


def test_bad_order_pull_keeps_a_random_spots_requirement():
    run = Run(random_spot())
    drawn = (run.state.requirement_number, run.state.requirement_side)
    run.set_out()
    run.pull(bad_order=True)
    assert (run.state.requirement_number, run.state.requirement_side) == drawn


def test_bad_order_pull_of_a_ready_car_is_a_normal_pull():
    run = Run(fixed_out(idle_days=1))
    run.set_out()
    run.advance(delay=False)
    run.advance(delay=False)
    assert run.pull(bad_order=True).state == v.IDLE
    assert run.state.position == 1


# --- a long run --------------------------------------------------------------------------------


def test_a_spot_cycles_for_a_long_time_without_getting_stuck():
    """Set out whenever awaiting, pull whenever ready: the spot keeps cycling."""
    run = Run(fixed_out(delay_chance=0.3, disruption_chance=0.1, idle_days=1), seed=42)
    completions = 0
    for _ in range(1000):
        if run.state.state == v.AWAITING_CAR:
            run.set_out()
        elif run.state.state == v.READY_FOR_PICKUP:
            run.pull()
            completions += 1
        run.advance()
    # A cycle takes 2 processing days + delays (avg 2/0.7 ≈ 2.9) + 1 idle day + ~0-1 day
    # waiting for the pull: roughly 4-5 days.
    assert 180 < completions < 260
