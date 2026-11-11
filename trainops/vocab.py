"""The plain words used in every value a person reads or types (spec Section 16).

All words are sentence case ("Ready for pickup", "Not tracked"). Typed words
are matched without regard to capitals or extra spaces, and are always
stored and shown in the canonical spelling defined here.
"""

from collections.abc import Iterable

# Directions toward the two worlds.
EAST = "East"
WEST = "West"
SIDES = (EAST, WEST)

# Spot direction.
INCOMING = "Incoming"
OUTGOING = "Outgoing"
SPOT_DIRECTIONS = (INCOMING, OUTGOING)

# Spot requirement mode.
FIXED = "Fixed"
RANDOM = "Random"
REQUIREMENT_MODES = (FIXED, RANDOM)

# Spot states (spec Section 5).
AWAITING_CAR = "Awaiting car"
PROCESSING = "Processing"
READY_FOR_PICKUP = "Ready for pickup"
IDLE = "Idle"  # after a pull, the industry doesn't want a car for idle_days
SPOT_STATES = (AWAITING_CAR, PROCESSING, READY_FOR_PICKUP, IDLE)

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
AT_WORLD = "World"
AT_YARD = "Yard"
AT_SPOT = "Spot"
AT_TRAIN = "Train"
AT_STORAGE = "Storage"
LOCATION_KINDS = (AT_WORLD, AT_YARD, AT_SPOT, AT_TRAIN, AT_STORAGE)

# Car loads.
LOADED = "Loaded"
EMPTY = "Empty"
NOT_TRACKED = "Not tracked"
LOADS = (LOADED, EMPTY, NOT_TRACKED)

# Engine pools.
POOL_LOCAL = "Local"
POOL_SWITCHER = "Switcher"
POOL_MANIFEST = "Manifest"
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


def same_words(a: str, b: str) -> bool:
    """True if two pieces of text are the same apart from capitals and spacing.

    Used for car types: a "Boxcar" car serves a "boxcar" spot.
    """
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def both(items: Iterable[str]) -> str:
    """Join items for a message: "mark and type", "a, b and c"."""
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def either(choices: Iterable[str]) -> str:
    """Join choices for a message: "East or West", "a, b or c"."""
    items = list(choices)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


# Signals (spec Section 13). Sources: web page buttons now, ESP32 nodes later.
WEST_CHORE_DONE = "West chore done"
EAST_CHORE_DONE = "East chore done"
JOB_A_DONE = "Job A done"
PULL_DONE = "Pull done"  # per spot
SET_OUT_DONE = "Set-out done"  # per spot
LOCAL_BACK = "Local back in yard"
JOB_B_DONE = "Job B done"
JOB_C_DONE = "Job C done"
SESSION_COMPLETE = "Session complete"
SIGNALS = (
    WEST_CHORE_DONE,
    EAST_CHORE_DONE,
    JOB_A_DONE,
    PULL_DONE,
    SET_OUT_DONE,
    LOCAL_BACK,
    JOB_B_DONE,
    JOB_C_DONE,
    SESSION_COMPLETE,
)
SPOT_SIGNALS = (PULL_DONE, SET_OUT_DONE)

# The jobs of a session, in order (what the page shows as the current job).
JOB_CHORES = "Pre-session chores"
JOB_A = "Job A"
JOB_LOCAL = "Local"
JOB_B = "Job B"
JOB_C = "Job C"
JOB_END = "Session complete"
