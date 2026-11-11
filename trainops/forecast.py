"""Demand forecast (spec Section 10): which spots need a car on a given day.

Cars for the local are chosen a day before they are used, so at each day
advance the planner (step 7) asks two questions:

- `for_today`: which spots need a car during today's local. The East-supplied
  part is served by today's Westbound Local block (cut by Switch westbound before the
  local runs); outgoing spots are served first by held empties on Locals.
- `for_tomorrow`: which spots will need a car during tomorrow's local,
  assuming today's local does all its listed work. The West-supplied part is
  served by today's Eastbound Local block; the East-supplied part must ride
  East on today's Eastbound manifest and come back in tomorrow's Westbound.

A spot needs a car on a day if, during that day's local, it is
- Awaiting car already, or
- Ready for pickup with no idle days: pulled and refilled on the same visit
  (a "swap"; the spot waits from the day of the pull), or
- Processing with a Bad order car: the pull puts it back to Awaiting car
  with its original place in line and the same requirement.

The forecast reports what the spots need, not how it will be met: netting
out cars already on the Locals track (undelivered cars still assigned to a
spot, held empties) and choosing cars is train planning (step 7).

A random spot whose requirement isn't drawn yet can't be forecast. That
only happens tomorrow, for a spot refilled today that will be ready again
tomorrow with no idle days (base processing 1 day). It is listed in
`not_drawn`, gets no car planned, and waits about a day like any shortage
(confirmed 2026-11-11).

Everything here is pure: config + spot states in, a Forecast out.
"""

from __future__ import annotations

import random
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from trainops import spots
from trainops import vocab as v
from trainops.config import Config, Spot
from trainops.db import SpotState


@dataclass(frozen=True)
class Demand:
    """One spot that needs one car on the forecast day."""

    spot_id: str
    car_type: str
    direction: str  # Incoming | Outgoing
    side: str  # East | West: Incoming = the world the loaded car comes from;
    #             Outgoing = scheduled destination (where the empty comes from, unless a held empty covers it)
    waiting_since_day: int  # place in line: oldest first
    swap: bool  # the spot is pulled first, on the same visit

    @property
    def load(self) -> str:
        """The load the car must arrive with."""
        return v.LOADED if self.direction == v.INCOMING else v.EMPTY


@dataclass(frozen=True)
class Forecast:
    day: int
    demands: tuple[Demand, ...]  # oldest waiting first, then config order
    not_drawn: tuple[str, ...] = ()  # random spots that will need a car whose requirement isn't drawn yet

    def from_side(self, side: str) -> tuple[Demand, ...]:
        """The demands supplied from one world (East or West)."""
        return tuple(d for d in self.demands if d.side == side)

    def for_spot(self, spot_id: str) -> Demand | None:
        return next((d for d in self.demands if d.spot_id == spot_id), None)


def for_today(
    config: Config,
    states: Mapping[str, SpotState],
    day: int,
    bad_order_spots: Collection[str] = (),
) -> Forecast:
    """Spots needing a car during today's local. Call after the day advance.

    `bad_order_spots`: spots holding a Bad order car (today's local pulls it).
    """
    return _forecast(
        config,
        day,
        ((spot, states[spot.spot_id], spot.spot_id in bad_order_spots) for spot in config.spots),
    )


def for_tomorrow(
    config: Config,
    states: Mapping[str, SpotState],
    day: int,
    served_today: Collection[str],
    bad_order_spots: Collection[str] = (),
) -> Forecast:
    """Spots needing a car during tomorrow's local (day + 1).

    Assumes today's local does all its listed work: every Ready for pickup
    spot and every Bad order car is pulled, and every spot in
    `served_today` gets its car set out (the spots today's planning found a
    car for; the rest stay Awaiting car).
    """
    today = for_today(config, states, day, bad_order_spots)
    needing = {d.spot_id for d in today.demands}
    unexpected = [config.spot(s).label for s in served_today if s not in needing]
    if unexpected:
        raise ValueError(f"Not needing a car today: {v.both(sorted(unexpected))}.")

    projected = []
    for spot in config.spots:
        state = states[spot.spot_id]
        bad_order = spot.spot_id in bad_order_spots
        if state.state == v.READY_FOR_PICKUP or (bad_order and state.state == v.PROCESSING):
            state = spots.pull(spot, state, day, bad_order=bad_order)
        if spot.spot_id in served_today:
            state = spots.set_out(spot, state)
        state = spots.preview_advance(spot, state, day + 1)
        projected.append((spot, state, False))  # Bad order cars are gone after today
    return _forecast(config, day + 1, projected)


def in_line(demands: Iterable[Demand], rng: random.Random) -> list[Demand]:
    """Demands in the order cars are given out when short: oldest waiting first,
    ties in random order (spec Section 5, shortage)."""
    shuffled = list(demands)
    rng.shuffle(shuffled)
    return sorted(shuffled, key=lambda d: d.waiting_since_day)


# --- internals -------------------------------------------------------------------------


def _forecast(
    config: Config, day: int, spot_states: Iterable[tuple[Spot, SpotState, bool]]
) -> Forecast:
    demands: list[Demand] = []
    not_drawn: list[str] = []
    for spot, state, bad_order in spot_states:
        found = _spot_demand(spot, state, day, bad_order)
        if found is _NOT_DRAWN:
            not_drawn.append(spot.spot_id)
        elif found is not None:
            demands.append(found)
    demands.sort(key=lambda d: d.waiting_since_day)  # stable: ties keep config order
    return Forecast(day, tuple(demands), tuple(not_drawn))


_NOT_DRAWN = object()


def _spot_demand(spot: Spot, state: SpotState, day: int, bad_order: bool):
    """The spot's Demand on `day`, None if it needs no car, or _NOT_DRAWN."""
    if state.state == v.AWAITING_CAR:
        wanted, since, swap = spots.need(spot, state), state.waiting_since_day, False
    elif state.state == v.PROCESSING and bad_order:
        wanted, since, swap = spots.need(spot, state), state.waiting_since_day, True
    elif state.state == v.READY_FOR_PICKUP and spots.need(spot, state).idle_days == 0:
        wanted, since, swap = spots.upcoming_need(spot, state), day, True
    else:
        return None
    if wanted is None:
        return _NOT_DRAWN
    return Demand(spot.spot_id, wanted.car_type, wanted.direction, wanted.side, since, swap)
