"""Spot states versus the configuration (spec Section 16.1, as agreed 2026-11-11).

Spot states are created only at cold start (`create_spot_states`). At every
start-up `check_config` compares the configuration with what was recorded at
the last cold start.

These changes need a cold start (the program refuses to run until one is done):
- an industry or spot added or removed, or an id / spot_id changed
- a spot's mode (Fixed / Random), car type or direction changed
- a random spot's list of possible requirements changed (one added or removed,
  or one's car type or direction changed)

Everything else takes effect without one: names, settings, processing days,
delay / disruption chances, idle days, weights and patterns. If a pattern got
shorter, the spot's position wraps around.
"""

from __future__ import annotations

from dataclasses import replace

from trainops import vocab as v
from trainops.config import Config, Spot
from trainops.db import Database, SpotState


class ColdStartNeeded(Exception):
    """The database doesn't match the configuration; `reasons` says why."""

    def __init__(self, reasons: list[str]):
        self.reasons = list(reasons)
        head = "A cold start is needed before the program can run:"
        super().__init__("\n".join([head] + [f"  - {r}" for r in self.reasons]))


def spot_identity(spot: Spot) -> str:
    """What about a spot needs a cold start to change, in plain words.

    For example "Fixed: boxcar, Outgoing" or
    "Random: boxcar, Incoming; covered hopper, Outgoing".
    """
    if spot.requirement_mode == v.FIXED:
        return f"{v.FIXED}: {spot.fixed.car_type}, {spot.fixed.direction}"
    parts = "; ".join(f"{r.car_type}, {r.direction}" for r in spot.possible_requirements)
    return f"{v.RANDOM}: {parts}"


def create_spot_states(db: Database, config: Config) -> None:
    """Give every spot a fresh state. Cold start only; call inside its transaction."""
    day = db.session().day
    for spot in config.spots:
        db.put_spot_state(
            SpotState.fresh(
                spot.spot_id, day, industry_id=spot.industry_id, identity=spot_identity(spot)
            )
        )


def check_config(db: Database, config: Config) -> list[str]:
    """Check the configuration against the last cold start.

    Raises ColdStartNeeded listing every difference that needs one. Otherwise
    applies the changes that don't (pattern wrap-around) in one transaction
    and returns plain-language notes about them.
    """
    saved = db.spot_states()
    if not saved:
        raise ColdStartNeeded(["no cold start has been done yet."])

    reasons: list[str] = []
    for spot in config.spots:
        state = saved.get(spot.spot_id)
        if state is None:
            reasons.append(f"{spot.label} is new.")
            continue
        if state.industry_id != spot.industry_id:
            reasons.append(
                f"{spot.label}: its industry id changed from '{state.industry_id}' "
                f"to '{spot.industry_id}'."
            )
        identity = spot_identity(spot)
        if identity.casefold() != state.identity.casefold():
            reasons.append(f"{spot.label} changed from '{state.identity}' to '{identity}'.")
    for spot_id in saved:
        if spot_id not in config.spots_by_id:
            reasons.append(f"the spot with id '{spot_id}' was removed.")
    if reasons:
        raise ColdStartNeeded(reasons)

    notes: list[str] = []
    with db.transaction():
        for spot in config.spots:
            state = saved[spot.spot_id]
            pattern = spot.fixed.pattern if spot.fixed else ()
            if pattern and state.position >= len(pattern):
                wrapped = state.position % len(pattern)
                db.put_spot_state(replace(state, position=wrapped))
                notes.append(
                    f"{spot.label}: pattern is shorter now; position {state.position + 1} "
                    f"wraps around to {wrapped + 1}."
                )
    return notes
