"""Bring saved spot states in line with the configuration (spec Section 16.1).

Runs whenever the program starts with a configuration, in one transaction.
Runtime state is never reset just because the configuration was reloaded.
The rules:

- A spot new in the configuration gets a fresh state: awaiting a car,
  waiting since today.
- A spot removed from the configuration is reported; its saved state is
  kept (so it comes back if the spot is restored) but ignored. Any car at
  that spot or assigned to it is reported too.
- If an outgoing spot's pattern got shorter, its position wraps around.

Two more cases follow from changing a spot's requirements:

- A random spot whose drawn requirement no longer exists (the list got
  shorter, or the spot used to be fixed) is reset to awaiting a car, so it
  draws again. A car still at the spot is reported, to be moved with the
  edit tool.
- A spot changed from random to fixed drops its random-draw fields.

A day-ahead random draw that no longer exists is simply cleared; it is
rolled again at the next day advance.
"""

from __future__ import annotations

from dataclasses import replace

from trainops import vocab as v
from trainops.config import Config, Spot
from trainops.db import Database, SpotState


def reconcile_spot_states(db: Database, config: Config) -> list[str]:
    """Update spot states for this configuration. Returns plain-language notes."""
    notes: list[str] = []
    with db.transaction():
        day = db.session().day
        saved = db.spot_states()

        for spot in config.spots:
            state = saved.get(spot.spot_id)
            if state is None:
                db.put_spot_state(SpotState.fresh(spot.spot_id, day))
                notes.append(f"{spot.label}: new spot, now awaiting a car.")
                continue
            new_state, spot_notes = _fit_to_config(db, spot, state, day)
            if new_state != state:
                db.put_spot_state(new_state)
            notes.extend(spot_notes)

        for spot_id in saved:
            if spot_id in config.spots_by_id:
                continue
            notes.append(
                f"The spot with id '{spot_id}' is no longer in the configuration. "
                f"Its saved state is kept but ignored."
            )
            for car in db.cars():
                if car.loc_kind == v.AT_SPOT and car.loc_ref == spot_id:
                    notes.append(
                        f"  Car {car.label} is still at that spot — move it with the edit tool."
                    )
                if car.assigned_spot == spot_id:
                    notes.append(
                        f"  Car {car.label} is assigned to that spot — fix it with the edit tool."
                    )
    return notes


def _fit_to_config(
    db: Database, spot: Spot, state: SpotState, day: int
) -> tuple[SpotState, list[str]]:
    notes: list[str] = []

    if spot.requirement_mode == v.FIXED:
        if state.requirement_number is not None or state.next_requirement_number is not None:
            state = replace(
                state,
                requirement_number=None,
                requirement_side=None,
                next_requirement_number=None,
                next_requirement_side=None,
            )
            notes.append(f"{spot.label}: now a fixed spot; it follows its fixed requirement.")
        pattern = spot.fixed.pattern
        if pattern and state.position >= len(pattern):
            wrapped = state.position % len(pattern)
            notes.append(
                f"{spot.label}: pattern is shorter now; position {state.position + 1} "
                f"wraps around to {wrapped + 1}."
            )
            state = replace(state, position=wrapped)
        return state, notes

    # Random spot.
    count = len(spot.possible_requirements)
    if state.next_requirement_number is not None and state.next_requirement_number > count:
        state = replace(state, next_requirement_number=None, next_requirement_side=None)

    drawn = state.requirement_number
    lost_draw = (drawn is not None and drawn > count) or (
        drawn is None and state.state != v.AWAITING_CAR
    )
    if lost_draw:
        state = replace(
            SpotState.fresh(spot.spot_id, day),
            position=state.position,
            next_requirement_number=state.next_requirement_number,
            next_requirement_side=state.next_requirement_side,
        )
        notes.append(
            f"{spot.label}: its current requirement is no longer in the configuration; "
            f"the spot is reset to awaiting a car and will draw a new one."
        )
        car_there = db.cars_at(v.AT_SPOT, spot.spot_id)
        for car in car_there:
            notes.append(
                f"  Car {car.label} is still at that spot — move it with the edit tool."
            )
    return state, notes
