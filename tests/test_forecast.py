"""Step 6: demand forecast."""

import random
from dataclasses import replace

import pytest

from trainops import spots
from trainops import vocab as v
from trainops.config import load_config, parse_config
from trainops.db import SpotState
from trainops.forecast import Demand, Forecast, for_today, for_tomorrow, in_line


def make_config(*spot_dicts):
    return parse_config({"industries": [{"id": "mill", "name": "Mill", "spots": list(spot_dicts)}]})


def fixed_in(spot_id="pit", **changes):
    spot = {
        "spot_id": spot_id,
        "name": spot_id.title(),
        "requirement_mode": "fixed",
        "car_type": "covered hopper",
        "direction": "incoming",
        "source": "West",
        "base_processing_days": 1,
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
        "pattern": ["East", "West"],
        "base_processing_days": 1,
    }
    spot.update(changes)
    return spot


def random_spot(spot_id="team", base=1, idle=0):
    return {
        "spot_id": spot_id,
        "name": spot_id.title(),
        "requirement_mode": "random",
        "possible_requirements": [
            {
                "car_type": "boxcar",
                "direction": "incoming",
                "source_weights": {"East": 1},
                "base_processing_days": base,
                "idle_days": idle,
            },
            {
                "car_type": "tank car",
                "direction": "outgoing",
                "destination_weights": {"West": 1},
                "base_processing_days": base,
                "idle_days": idle,
            },
        ],
    }


def state(spot_id, spot_state, **fields):
    base = SpotState(spot_id=spot_id, state=spot_state, industry_id="mill", identity="test")
    return replace(base, **{"next_delay": False, **fields})


def one(config, st, day=5, **kw):
    """Today's forecast for a one-spot config."""
    return for_today(config, {st.spot_id: st}, day, **kw)


def one_tomorrow(config, st, day=5, served=(), **kw):
    return for_tomorrow(config, {st.spot_id: st}, day, served, **kw)


# --- today ----------------------------------------------------------------------------


def test_awaiting_spot_needs_a_car_with_its_place_in_line():
    config = make_config(fixed_in())
    forecast = one(config, state("pit", v.AWAITING_CAR, waiting_since_day=3))
    assert forecast == Forecast(5, (Demand("pit", "covered hopper", v.INCOMING, v.WEST, 3, False),))
    assert forecast.demands[0].load == v.LOADED


@pytest.mark.parametrize(
    "spot_state, days_left", [(v.PROCESSING, 1), (v.IDLE, 1)]
)
def test_processing_and_idle_spots_need_nothing_today(spot_state, days_left):
    config = make_config(fixed_in())
    forecast = one(config, state("pit", spot_state, days_left=days_left, waiting_since_day=1))
    assert forecast.demands == () and forecast.not_drawn == ()


def test_ready_spot_with_no_idle_days_is_a_swap_waiting_from_today():
    config = make_config(fixed_in())
    forecast = one(config, state("pit", v.READY_FOR_PICKUP, waiting_since_day=1), day=7)
    assert forecast.demands == (Demand("pit", "covered hopper", v.INCOMING, v.WEST, 7, True),)


def test_ready_spot_with_idle_days_needs_nothing_today():
    config = make_config(fixed_in(idle_days=1))
    assert one(config, state("pit", v.READY_FOR_PICKUP)).demands == ()


def test_outgoing_swap_uses_the_next_pattern_entry():
    # Position already moved on when processing completed: entry 1 = West.
    config = make_config(fixed_out())
    forecast = one(config, state("door", v.READY_FOR_PICKUP, position=1, out_dest=v.EAST))
    demand = forecast.demands[0]
    assert (demand.side, demand.direction, demand.load) == (v.WEST, v.OUTGOING, v.EMPTY)


def test_random_swap_uses_the_day_early_draw():
    config = make_config(random_spot())
    st = state(
        "team",
        v.READY_FOR_PICKUP,
        requirement_number=1,
        requirement_side=v.EAST,
        next_requirement_number=2,
        next_requirement_side=v.WEST,
    )
    demand = one(config, st).demands[0]
    assert (demand.car_type, demand.direction, demand.side) == ("tank car", v.OUTGOING, v.WEST)


def test_bad_order_car_in_processing_spot_is_a_swap_keeping_its_place_in_line():
    config = make_config(fixed_in(base_processing_days=3))
    st = state("pit", v.PROCESSING, days_left=2, waiting_since_day=2)
    assert one(config, st).demands == ()
    demand = one(config, st, bad_order_spots={"pit"}).demands[0]
    assert (demand.waiting_since_day, demand.swap) == (2, True)


def test_bad_order_car_at_ready_spot_is_an_ordinary_pull():
    config = make_config(fixed_in(idle_days=1))
    st = state("pit", v.READY_FOR_PICKUP)
    assert one(config, st, bad_order_spots={"pit"}).demands == ()


def test_demands_oldest_first_then_config_order_and_by_side():
    config = make_config(
        fixed_in("a", source="East"),
        fixed_in("b"),
        fixed_out("c"),
    )
    states = {
        "a": state("a", v.AWAITING_CAR, waiting_since_day=4),
        "b": state("b", v.AWAITING_CAR, waiting_since_day=4),
        "c": state("c", v.AWAITING_CAR, waiting_since_day=2),
    }
    forecast = for_today(config, states, 5)
    assert [d.spot_id for d in forecast.demands] == ["c", "a", "b"]
    assert [d.spot_id for d in forecast.from_side(v.EAST)] == ["c", "a"]
    assert [d.spot_id for d in forecast.from_side(v.WEST)] == ["b"]
    assert forecast.for_spot("b").side == v.WEST
    assert forecast.for_spot("zzz") is None


def test_in_line_breaks_ties_at_random_but_keeps_oldest_first():
    demands = [Demand(f"s{i}", "boxcar", v.INCOMING, v.EAST, 3 if i else 1, False) for i in range(6)]
    orders = set()
    for seed in range(20):
        lined = in_line(demands, random.Random(seed))
        assert lined[0].spot_id == "s0"
        orders.add(tuple(d.spot_id for d in lined))
    assert len(orders) > 1


# --- tomorrow -------------------------------------------------------------------------


def test_processing_finishing_tonight_with_no_idle_is_a_swap_tomorrow():
    config = make_config(fixed_in())
    st = state("pit", v.PROCESSING, days_left=1, waiting_since_day=1)
    forecast = one_tomorrow(config, st, day=5)
    assert forecast.day == 6
    assert forecast.demands == (Demand("pit", "covered hopper", v.INCOMING, v.WEST, 6, True),)


def test_the_day_early_delay_roll_holds_the_countdown():
    config = make_config(fixed_in())
    st = state("pit", v.PROCESSING, days_left=1, next_delay=True)
    assert one_tomorrow(config, st).demands == ()


def test_idle_ending_tonight_needs_a_car_tomorrow():
    config = make_config(fixed_in(idle_days=2))
    assert one_tomorrow(config, state("pit", v.IDLE, days_left=2)).demands == ()
    demand = one_tomorrow(config, state("pit", v.IDLE, days_left=1), day=5).demands[0]
    assert (demand.waiting_since_day, demand.swap) == (6, False)


def test_ready_with_idle_day_pulled_today_needs_a_car_tomorrow():
    config = make_config(fixed_in(idle_days=1))
    demand = one_tomorrow(config, state("pit", v.READY_FOR_PICKUP), day=5).demands[0]
    assert (demand.waiting_since_day, demand.swap) == (6, False)


def test_unserved_spot_still_waits_tomorrow_with_its_place_in_line():
    config = make_config(fixed_in())
    demand = one_tomorrow(config, state("pit", v.AWAITING_CAR, waiting_since_day=2)).demands[0]
    assert (demand.waiting_since_day, demand.swap) == (2, False)


def test_served_spot_one_day_processing_is_a_swap_tomorrow():
    config = make_config(fixed_in())
    st = state("pit", v.AWAITING_CAR, waiting_since_day=2)
    demand = one_tomorrow(config, st, day=5, served={"pit"}).demands[0]
    assert (demand.waiting_since_day, demand.swap) == (6, True)


def test_served_spot_two_day_processing_needs_nothing_tomorrow():
    config = make_config(fixed_in(base_processing_days=2))
    st = state("pit", v.AWAITING_CAR, waiting_since_day=2)
    assert one_tomorrow(config, st, served={"pit"}).demands == ()


def test_daily_swap_at_outgoing_spot_follows_the_pattern_each_day():
    # Ready today (position already on entry 1 = West); swapped today; ready again
    # tomorrow, when the pattern moves on to entry 0 = East.
    config = make_config(fixed_out())
    st = state("door", v.READY_FOR_PICKUP, position=1, out_dest=v.EAST)
    assert one(config, st).demands[0].side == v.WEST
    tomorrow = one_tomorrow(config, st, served={"door"})
    assert tomorrow.demands[0].side == v.EAST


def test_random_spot_refilled_today_and_ready_tomorrow_is_not_drawn_yet():
    config = make_config(random_spot(base=1, idle=0))
    st = state(
        "team",
        v.READY_FOR_PICKUP,
        requirement_number=1,
        requirement_side=v.EAST,
        next_requirement_number=2,
        next_requirement_side=v.WEST,
    )
    tomorrow = one_tomorrow(config, st, served={"team"})
    assert tomorrow.demands == ()
    assert tomorrow.not_drawn == ("team",)
    # Not served today: it keeps waiting for the requirement it took at the pull.
    tomorrow = one_tomorrow(config, st, day=5)
    assert tomorrow.not_drawn == ()
    assert tomorrow.demands[0].car_type == "tank car"
    assert tomorrow.demands[0].waiting_since_day == 5


def test_random_spot_idle_ending_tonight_uses_its_day_early_draw():
    config = make_config(random_spot(idle=1))
    st = state(
        "team",
        v.IDLE,
        days_left=1,
        requirement_number=1,
        requirement_side=v.EAST,
        next_requirement_number=2,
        next_requirement_side=v.WEST,
    )
    demand = one_tomorrow(config, st).demands[0]
    assert (demand.car_type, demand.side) == ("tank car", v.WEST)


def test_bad_order_pull_from_processing_keeps_its_place_tomorrow():
    config = make_config(fixed_in(base_processing_days=3))
    st = state("pit", v.PROCESSING, days_left=2, waiting_since_day=2)
    demand = one_tomorrow(config, st, bad_order_spots={"pit"}).demands[0]
    assert (demand.waiting_since_day, demand.swap) == (2, False)
    # Refilled today after the bad-order pull: processing again, nothing tomorrow.
    assert one_tomorrow(config, st, served={"pit"}, bad_order_spots={"pit"}).demands == ()


def test_serving_a_spot_that_needs_no_car_today_is_refused():
    config = make_config(fixed_in())
    with pytest.raises(ValueError, match="Not needing a car today: Mill, Pit"):
        one_tomorrow(config, state("pit", v.PROCESSING, days_left=2), served={"pit"})


# --- the forecast matches what actually happens ---------------------------------------


def _play(config, seed, days, serve_chance):
    """Play days with real rolls; check each forecast against the next day."""
    rng = random.Random(seed)
    settings = config.settings
    states = {
        s.spot_id: spots.roll_ahead(
            s, SpotState.fresh(s.spot_id, 1, industry_id=s.industry_id, identity="x"), rng, settings
        )
        for s in config.spots
    }
    checked = not_drawn_seen = 0
    for day in range(1, days + 1):
        today = for_today(config, states, day)
        served = {d.spot_id for d in today.demands if rng.random() < serve_chance}
        predicted = for_tomorrow(config, states, day, served)

        # Today's local does its work: every Ready spot pulled, served spots set out.
        for spot in config.spots:
            st = states[spot.spot_id]
            if st.state == v.READY_FOR_PICKUP:
                st = spots.pull(spot, st, day)
            if spot.spot_id in served:
                st = spots.set_out(spot, st)
            states[spot.spot_id] = spots.advance(spot, st, rng, settings, day + 1)

        actual = for_today(config, states, day + 1)
        drawn_late = set(predicted.not_drawn)
        assert {d.spot_id for d in actual.demands} >= drawn_late
        assert [d for d in actual.demands if d.spot_id not in drawn_late] == list(
            predicted.demands
        )
        checked += len(predicted.demands)
        not_drawn_seen += len(drawn_late)
    return checked, not_drawn_seen


@pytest.mark.parametrize("serve_chance", [1.0, 0.6])
def test_forecast_matches_the_next_day_for_the_sample_industries(samples_dir, serve_chance):
    config = load_config(samples_dir / "config.yaml")
    checked, _ = _play(config, seed=11, days=300, serve_chance=serve_chance)
    assert checked > 300


def test_forecast_matches_the_next_day_with_daily_random_spot():
    config = make_config(random_spot("a", base=1, idle=0), random_spot("b", base=2, idle=1), fixed_out())
    checked, not_drawn_seen = _play(config, seed=3, days=300, serve_chance=0.8)
    assert checked > 300 and not_drawn_seen > 0
