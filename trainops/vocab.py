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

# Spot states (spec Section 5).
AWAITING_CAR = "awaiting car"
PROCESSING = "processing"
READY_FOR_PICKUP = "ready for pickup"
COOLDOWN = "cooldown"
SPOT_STATES = (AWAITING_CAR, PROCESSING, READY_FOR_PICKUP, COOLDOWN)

# Places (spec Section 16.3). A location is a kind plus one of these names.
EAST_STAGING = "East staging"  # the hidden return loop
WEST_STAGING = "West staging"
WORLDS = (EAST_STAGING, WEST_STAGING)

EASTBOUND_TRACK = "Eastbound track"
WESTBOUND_TRACK = "Westbound track"
LOCALS_TRACK = "Locals track"
YARD_TRACKS = (EASTBOUND_TRACK, WESTBOUND_TRACK, LOCALS_TRACK)

WESTBOUND_MANIFEST = "Westbound manifest"
EASTBOUND_MANIFEST = "Eastbound manifest"
LOCAL = "Local"
TRAINS = (WESTBOUND_MANIFEST, EASTBOUND_MANIFEST, LOCAL)

STORAGE = "Storage"  # engines only

# Location kinds.
AT_WORLD = "world"
AT_YARD = "yard"
AT_SPOT = "spot"
AT_TRAIN = "train"
AT_STORAGE = "storage"
LOCATION_KINDS = (AT_WORLD, AT_YARD, AT_SPOT, AT_TRAIN, AT_STORAGE)

# Car loads.
LOADED = "loaded"
EMPTY = "empty"
NOT_TRACKED = "not tracked"
LOADS = (LOADED, EMPTY, NOT_TRACKED)

# Engine pools.
POOL_LOCAL = "local"
POOL_SWITCHER = "switcher"
POOL_MANIFEST = "manifest"
POOLS = (POOL_LOCAL, POOL_SWITCHER, POOL_MANIFEST)


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
