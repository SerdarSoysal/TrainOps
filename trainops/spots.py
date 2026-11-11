"""Spot logic (spec Section 5): the cycle every industry spot goes through.

    Awaiting car --(set-out done)--> Processing --(countdown ends at a day advance)-->
    Ready for pickup --(pull done)--> Idle (idle_days; skipped if 0) --> Awaiting car

These functions take a spot's configuration and saved state and return the
new state; they never touch the database. Signals (step 8) call `set_out`
and `pull`; the day advance calls `advance` for every spot.

Timing:
- Processing counts down one day at each day advance, unless that day's
  delay roll hits, which holds the countdown for a day. Delays can stack.
  The delay chance is the lower of the requirement's delay_chance and the
  delay_chance_max setting.
- When the countdown ends the spot is Ready for pickup. An outgoing spot's
  destination is fixed then: for a fixed spot pattern[position], flipped to
  the other side if the disruption roll hits; for a random spot the side
  drawn with the requirement. A fixed spot's position advances on every
  completion, disruption or not.
- Idle counts down one day at each day advance; at 0 the spot is Awaiting car
  again, waiting since that day.
- Rolled a day early (so the forecast is exact): the delay roll for the next
  day advance, and a random spot's next requirement (with its side). They
  are always applied to the spot's actual state at the time.
- A spot holding a Bad order car is frozen: nothing counts down until the
  car is pulled. A bad-order pull from a Processing spot returns it to
  Awaiting car with its original place in line, same requirement, and no
  pattern advance (the work was never done).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from trainops import vocab as v
from trainops.config import Settings, Spot
from trainops.db import SpotState


class SpotRuleError(Exception):
    """A spot can't do what was asked in its current state (plain language)."""


@dataclass(frozen=True)
class Need:
    """What a spot requires, in one shape for fixed and random spots."""

    car_type: str
    direction: str  # Incoming | Outgoing
    side: str  # Incoming: where the loaded car comes from. Outgoing: scheduled destination.
    base_processing_days: int
    delay_chance: float
    idle_days: int


# --- what a spot needs -----------------------------------------------------------------


def need(spot: Spot, state: SpotState) -> Need | None:
    """The requirement in effect now (None: a random spot with nothing drawn yet)."""
    if spot.requirement_mode == v.FIXED:
        fixed = spot.fixed
        if fixed.direction == v.INCOMING:
            side = fixed.source
        else:
            side = fixed.pattern[state.position % len(fixed.pattern)]
        return Need(
            fixed.car_type,
            fixed.direction,
            side,
            fixed.base_processing_days,
            fixed.delay_chance,
            fixed.idle_days,
        )
    return _random_need(spot, state.requirement_number, state.requirement_side)


def upcoming_need(spot: Spot, state: SpotState) -> Need | None:
    """The requirement the spot will have the next time it is Awaiting car.

    For a Ready or Idle random spot that is the draw made a day early; in
    every other case it is the requirement in effect now.
    """
    if spot.requirement_mode == v.RANDOM and state.state in (v.READY_FOR_PICKUP, v.IDLE):
        return _random_need(spot, state.next_requirement_number, state.next_requirement_side)
    return need(spot, state)


def next_draw_need(spot: Spot, state: SpotState) -> Need | None:
    """A random spot's day-early draw (None for a fixed spot or when not drawn)."""
    if spot.requirement_mode != v.RANDOM:
        return None
    return _random_need(spot, state.next_requirement_number, state.next_requirement_side)


def _random_need(spot: Spot, number: int | None, side: str | None) -> Need | None:
    if number is None:
        return None
    req = spot.possible_requirements[number - 1]
    return Need(
        req.car_type,
        req.direction,
        side,
        req.base_processing_days,
        req.delay_chance,
        req.idle_days,
    )


# --- signals ---------------------------------------------------------------------------


def set_out(spot: Spot, state: SpotState) -> SpotState:
    """A car was set out at the spot: it starts processing."""
    if state.state != v.AWAITING_CAR:
        raise SpotRuleError(
            f"{spot.label} is {state.state.lower()} — a car can only be set out there "
            f"when it is awaiting a car."
        )
    current = need(spot, state)
    if current is None:
        raise SpotRuleError(f"{spot.label} has no requirement drawn yet.")
    # waiting_since_day is kept: a bad-order pull puts the spot back in line there.
    return replace(state, state=v.PROCESSING, days_left=current.base_processing_days)


def pull(spot: Spot, state: SpotState, day: int, *, bad_order: bool = False) -> SpotState:
    """The car at the spot was pulled."""
    if bad_order and state.state == v.PROCESSING:
        return replace(state, state=v.AWAITING_CAR, days_left=None, out_dest=None)
    if state.state != v.READY_FOR_PICKUP:
        raise SpotRuleError(
            f"{spot.label} is {state.state.lower()} — a car can only be pulled from it "
            f"when it is ready for pickup."
        )
    idle_days = need(spot, state).idle_days
    if idle_days == 0:
        return _awaiting_car(spot, state, day)
    return replace(state, state=v.IDLE, days_left=idle_days, out_dest=None)


# --- day advance -----------------------------------------------------------------------


def advance(
    spot: Spot,
    state: SpotState,
    rng: random.Random,
    settings: Settings,
    new_day: int,
    *,
    frozen: bool = False,
) -> SpotState:
    """One day advance for one spot, then the rolls for the next day.

    `frozen` is True while a Bad order car sits at the spot.
    """
    if not frozen:
        state = _count_down(spot, state, new_day, rng)
    return roll_ahead(spot, state, rng, settings)


def preview_advance(spot: Spot, state: SpotState, new_day: int) -> SpotState:
    """The next day advance as the forecast sees it, without making any rolls.

    The countdowns use the delay already rolled a day early. A disruption
    is treated as not happening: it only changes where a finished car goes,
    not what the spot needs next. The next day's rolls are not made, so a
    random spot that has used up its day-early draw has no next requirement.
    """
    return _count_down(spot, state, new_day, None)


def roll_ahead(
    spot: Spot, state: SpotState, rng: random.Random, settings: Settings
) -> SpotState:
    """Make the day-early rolls: a random spot's draws, and the next delay roll.

    Also used at cold start, where a random spot draws its first requirement.
    """
    if spot.requirement_mode == v.RANDOM:
        if state.state == v.AWAITING_CAR and state.requirement_number is None:
            state = _take_next_draw(spot, state, rng)
        if state.next_requirement_number is None:
            number, side = _draw(spot, rng)
            state = replace(state, next_requirement_number=number, next_requirement_side=side)

    coming = upcoming_need(spot, state)
    chance = min(coming.delay_chance, settings.delay_chance_max) if coming else 0.0
    return replace(state, next_delay=rng.random() < chance)


# --- internals -------------------------------------------------------------------------


def _count_down(
    spot: Spot, state: SpotState, new_day: int, rng: random.Random | None
) -> SpotState:
    """The countdowns of one day advance (rng None: no disruption roll)."""
    if state.state == v.PROCESSING:
        days_left = state.days_left if state.next_delay else state.days_left - 1
        state = replace(state, days_left=days_left)
        if days_left <= 0:
            state = _complete(spot, state, rng)
    elif state.state == v.IDLE:
        days_left = state.days_left - 1
        state = replace(state, days_left=days_left)
        if days_left <= 0:
            state = _awaiting_car(spot, state, new_day)
    return state


def _complete(spot: Spot, state: SpotState, rng: random.Random | None) -> SpotState:
    """Processing finished: Ready for pickup, outgoing destination fixed."""
    out_dest = None
    position = state.position
    if spot.requirement_mode == v.FIXED:
        fixed = spot.fixed
        if fixed.direction == v.OUTGOING:
            out_dest = fixed.pattern[position % len(fixed.pattern)]
            if rng is not None and rng.random() < fixed.disruption_chance:
                out_dest = _other_side(out_dest)
            position = (position + 1) % len(fixed.pattern)
    else:
        current = need(spot, state)
        if current.direction == v.OUTGOING:
            out_dest = current.side
    return replace(
        state, state=v.READY_FOR_PICKUP, days_left=None, out_dest=out_dest, position=position
    )


def _awaiting_car(spot: Spot, state: SpotState, day: int) -> SpotState:
    """The spot wants a car again, from `day`; a random spot takes its next draw."""
    state = replace(
        state, state=v.AWAITING_CAR, days_left=None, out_dest=None, waiting_since_day=day
    )
    if spot.requirement_mode == v.RANDOM:
        state = replace(
            state,
            requirement_number=state.next_requirement_number,
            requirement_side=state.next_requirement_side,
            next_requirement_number=None,
            next_requirement_side=None,
        )
    return state


def _take_next_draw(spot: Spot, state: SpotState, rng: random.Random) -> SpotState:
    if state.next_requirement_number is not None:
        number, side = state.next_requirement_number, state.next_requirement_side
    else:
        number, side = _draw(spot, rng)
    return replace(
        state,
        requirement_number=number,
        requirement_side=side,
        next_requirement_number=None,
        next_requirement_side=None,
    )


def _draw(spot: Spot, rng: random.Random) -> tuple[int, str]:
    """Draw a random requirement (by weight) and its side (by side weights)."""
    reqs = spot.possible_requirements
    index = rng.choices(range(len(reqs)), weights=[r.weight for r in reqs])[0]
    req = reqs[index]
    side = rng.choices(v.SIDES, weights=[req.side_weights[s] for s in v.SIDES])[0]
    return index + 1, side


def _other_side(side: str) -> str:
    return v.WEST if side == v.EAST else v.EAST
