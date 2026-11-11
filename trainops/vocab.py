"""The plain words used in every value a person reads or types (spec Section 16).

Typed words are matched without regard to capitals or extra spaces, and are
always stored and shown in the canonical spelling defined here.
"""

from collections.abc import Iterable

# Directions toward the two worlds.
EAST = "East"
WEST = "West"
SIDES = (EAST, WEST)

# Spot direction.
INCOMING = "incoming"
OUTGOING = "outgoing"
SPOT_DIRECTIONS = (INCOMING, OUTGOING)

# Spot requirement mode.
FIXED = "fixed"
RANDOM = "random"
REQUIREMENT_MODES = (FIXED, RANDOM)


def match_word(value: object, choices: Iterable[str]) -> str | None:
    """Return the canonical spelling of `value` among `choices`, or None.

    Matching ignores capitals and collapses runs of spaces, so
    "  east   staging " matches "East staging".
    """
    if not isinstance(value, str):
        return None
    wanted = " ".join(value.split()).casefold()
    for choice in choices:
        if choice.casefold() == wanted:
            return choice
    return None


def either(choices: Iterable[str]) -> str:
    """Join choices for a message: "East or West", "a, b or c"."""
    items = list(choices)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]
