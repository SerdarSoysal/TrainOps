"""Load and check the configuration file (spec Sections 5 and 16.1).

The configuration is static while the program runs. `load_config` reads the
YAML file, checks every field, and returns a `Config`. If anything is wrong
it raises `ConfigError` listing every problem found, in plain language,
each prefixed with where it is, for example:

    Industry #1, Loading door 2: pattern contains 'Eest' — expected East or West

Words are matched regardless of capitals and stored in their canonical
spelling (see `vocab`). Optional fields and their defaults:
    settings (each one)      the defaults in DEFAULT_SETTINGS / DEFAULT_CAPACITY /
                             DEFAULT_DELAY_CHANCE_MAX
    disruption_chance        0
    delay_chance             0
    idle_days            0
    weight (random spots)    1
"""

from __future__ import annotations

import difflib
import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from trainops.vocab import (
    FIXED,
    INCOMING,
    OUTGOING,
    RANDOM,
    REQUIREMENT_MODES,
    SIDES,
    SPOT_DIRECTIONS,
    CHORE_FULL,
    CHORE_MODES,
    either,
    match_word,
)

# name: (default, smallest allowed)
DEFAULT_SETTINGS: dict[str, tuple[int, int]] = {
    "hold_days_on_locals": (2, 0),
    "eastbound_length_min": (12, 1),
    "eastbound_length_max": (20, 1),
    "train_nominal_max": (20, 1),
    "three_engines_from": (16, 1),
}
# Cap on every spot's delay_chance: the program uses the lower of the two.
# 1 means no extra cap. Lower it to make delays rarer everywhere at once.
DEFAULT_DELAY_CHANCE_MAX = 1.0
DEFAULT_CAPACITY: dict[str, int] = {
    "east_staging": 30,
    "west_staging": 70,
    "yard_track": 35,
}

TOP_FIELDS = ("settings", "industries")
INDUSTRY_FIELDS = ("id", "name", "spots")
SPOT_COMMON_FIELDS = ("spot_id", "name", "requirement_mode")
FIXED_ONLY_FIELDS = (
    "car_type",
    "direction",
    "source",
    "pattern",
    "disruption_chance",
    "base_processing_days",
    "delay_chance",
    "idle_days",
)
RANDOM_ONLY_FIELDS = ("possible_requirements",)
SPOT_FIELDS = SPOT_COMMON_FIELDS + FIXED_ONLY_FIELDS + RANDOM_ONLY_FIELDS
REQUIREMENT_FIELDS = (
    "car_type",
    "direction",
    "source_weights",
    "destination_weights",
    "weight",
    "base_processing_days",
    "delay_chance",
    "idle_days",
)


# --- the checked configuration ------------------------------------------


@dataclass(frozen=True)
class Capacity:
    east_staging: int
    west_staging: int
    yard_track: int


@dataclass(frozen=True)
class Settings:
    hold_days_on_locals: int
    eastbound_length_min: int
    eastbound_length_max: int
    train_nominal_max: int
    three_engines_from: int
    delay_chance_max: float  # caps every spot's delay_chance
    capacity: Capacity
    chore_mode: str = "Full"  # Full | Quick; the default for the page's chore toggle


@dataclass(frozen=True)
class FixedRequirement:
    """What a fixed-mode spot always needs."""

    car_type: str
    direction: str  # incoming | outgoing
    source: str | None  # incoming only: East | West
    pattern: tuple[str, ...]  # outgoing only: repeating destinations; () for incoming
    disruption_chance: float  # outgoing only; 0 for incoming
    base_processing_days: int
    delay_chance: float
    idle_days: int


@dataclass(frozen=True)
class RandomRequirement:
    """One requirement a random-mode spot can draw."""

    car_type: str
    direction: str  # incoming | outgoing
    # incoming: source_weights; outgoing: destination_weights. Always has East and West.
    side_weights: dict[str, float]
    weight: float
    base_processing_days: int
    delay_chance: float
    idle_days: int


@dataclass(frozen=True)
class Spot:
    spot_id: str
    name: str
    industry_id: str
    industry_name: str
    requirement_mode: str  # fixed | random
    fixed: FixedRequirement | None  # set for fixed spots
    possible_requirements: tuple[RandomRequirement, ...]  # set for random spots

    @property
    def label(self) -> str:
        """How operators see this spot: "Northfield Paper, Loading door 1"."""
        return f"{self.industry_name}, {self.name}"


@dataclass(frozen=True)
class Industry:
    id: str
    name: str
    spots: tuple[Spot, ...]


@dataclass(frozen=True)
class Config:
    settings: Settings
    industries: tuple[Industry, ...]
    spots_by_id: dict[str, Spot] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        spots = {s.spot_id: s for ind in self.industries for s in ind.spots}
        object.__setattr__(self, "spots_by_id", spots)

    @property
    def spots(self) -> tuple[Spot, ...]:
        return tuple(self.spots_by_id.values())

    def spot(self, spot_id: str) -> Spot:
        return self.spots_by_id[spot_id]


class ConfigError(Exception):
    """The configuration has one or more problems. `problems` lists them all."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        count = len(self.problems)
        head = (
            "The configuration has 1 problem:"
            if count == 1
            else f"The configuration has {count} problems:"
        )
        super().__init__("\n".join([head] + [f"  - {p}" for p in self.problems]))


# --- reading the file ----------------------------------------------------


class _DuplicateKeyError(yaml.constructor.ConstructorError):
    pass


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses a field written twice in the same section.

    Plain YAML silently keeps the last one, which hides typing mistakes.
    """


def _construct_unique_mapping(loader, node):
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise _DuplicateKeyError(
                None, None, f"'{key}' appears twice in the same section", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_config(path: str | Path) -> Config:
    """Read and check the configuration file. Raises ConfigError."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ConfigError([f"configuration file not found: {path}"]) from None
    except OSError as e:
        raise ConfigError([f"can't read configuration file {path}: {e.strerror}"]) from None

    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.MarkedYAMLError as e:
        where = path.name
        if e.problem_mark is not None:
            where += f", line {e.problem_mark.line + 1}"
        if isinstance(e, _DuplicateKeyError):
            message = e.problem
        else:
            message = f"the file isn't valid YAML ({e.problem})"
        raise ConfigError([f"{where}: {message}"]) from None
    except yaml.YAMLError as e:
        raise ConfigError([f"{path.name}: the file isn't valid YAML ({e})"]) from None

    if data is None:
        raise ConfigError([f"{path.name}: the file is empty"])
    return parse_config(data)


def parse_config(data: object) -> Config:
    """Check already-read configuration data. Raises ConfigError."""
    if not isinstance(data, dict):
        raise ConfigError(["the file must contain a 'settings' section and an 'industries' list"])
    ck = _Checker()
    ck.unknown_fields("Configuration", data, TOP_FIELDS)
    settings = _check_settings(ck, data.get("settings"))
    industries = _check_industries(ck, data.get("industries"))
    if ck.problems:
        raise ConfigError(ck.problems)
    return Config(settings=settings, industries=tuple(industries))


# --- field checking -------------------------------------------------------

_MISSING = object()


def _show(value: object) -> str:
    if isinstance(value, str):
        return f"'{value}'"
    if value is None:
        return "nothing"
    return str(value)


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _clean_text(value: object) -> str | None:
    """Text with extra spaces collapsed, or None if not usable text."""
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    return None


class _Checker:
    """Collects problems; each reader returns None when the value is bad."""

    def __init__(self) -> None:
        self.problems: list[str] = []

    def problem(self, where: str, message: str) -> None:
        self.problems.append(f"{where}: {message}")

    def unknown_fields(self, where: str, data: dict, allowed: tuple[str, ...]) -> None:
        for key in data:
            if key in allowed:
                continue
            if key == "position":
                self.problem(
                    where,
                    "'position' is kept by the program while it runs, not set in the "
                    "configuration — remove it",
                )
                continue
            close = difflib.get_close_matches(str(key), allowed, n=1)
            hint = f" (did you mean '{close[0]}'?)" if close else ""
            self.problem(where, f"unknown field '{key}'{hint}")

    def text(self, where: str, data: dict, key: str) -> str | None:
        if data.get(key) is None:
            self.problem(where, f"missing '{key}'")
            return None
        value = _clean_text(data[key])
        if value is None:
            self.problem(where, f"'{key}' must be text (found {_show(data[key])})")
        return value

    def whole(
        self, where: str, data: dict, key: str, minimum: int, default: object = _MISSING
    ) -> int | None:
        if data.get(key) is None:
            if default is _MISSING:
                self.problem(where, f"missing '{key}'")
                return None
            return default  # type: ignore[return-value]
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            self.problem(
                where, f"'{key}' must be a whole number of {minimum} or more (found {_show(value)})"
            )
            return None
        return value

    def chance(
        self, where: str, data: dict, key: str, *, allow_one: bool = True, default: float = 0.0
    ) -> float | None:
        if data.get(key) is None:
            return default
        value = data[key]
        if _is_number(value) and 0 <= value and (value <= 1 if allow_one else value < 1):
            return float(value)
        rule = "a number from 0 to 1" if allow_one else "a number from 0 up to (but not including) 1"
        self.problem(where, f"'{key}' must be {rule} (found {_show(value)})")
        return None

    def positive(self, where: str, data: dict, key: str, default: float) -> float | None:
        if data.get(key) is None:
            return default
        value = data[key]
        if _is_number(value) and value > 0:
            return float(value)
        self.problem(where, f"'{key}' must be a number above 0 (found {_show(value)})")
        return None

    def word(self, where: str, data: dict, key: str, choices: tuple[str, ...]) -> str | None:
        if data.get(key) is None:
            self.problem(where, f"missing '{key}' — expected {either(choices)}")
            return None
        value = match_word(data[key], choices)
        if value is None:
            self.problem(where, f"'{key}' is {_show(data[key])} — expected {either(choices)}")
        return value


# --- settings ---------------------------------------------------------------


def _check_settings(ck: _Checker, raw: object) -> Settings | None:
    where = "Settings"
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        ck.problem(where, "must be a section of named values")
        return None
    start = len(ck.problems)
    ck.unknown_fields(where, raw, (*DEFAULT_SETTINGS, "delay_chance_max", "capacity",
                                   "chore_mode"))
    values: dict[str, object] = {
        key: ck.whole(where, raw, key, minimum, default=default)
        for key, (default, minimum) in DEFAULT_SETTINGS.items()
    }
    values["delay_chance_max"] = ck.chance(
        where, raw, "delay_chance_max", default=DEFAULT_DELAY_CHANCE_MAX
    )
    values["chore_mode"] = (
        ck.word(where, raw, "chore_mode", CHORE_MODES) if raw.get("chore_mode") is not None
        else CHORE_FULL
    )

    cap_where = "Settings, capacity"
    cap_raw = raw.get("capacity")
    if cap_raw is None:
        cap_raw = {}
    if not isinstance(cap_raw, dict):
        ck.problem(cap_where, "must be a section of named values")
        cap_raw = {}
    ck.unknown_fields(cap_where, cap_raw, tuple(DEFAULT_CAPACITY))
    capacity = {
        key: ck.whole(cap_where, cap_raw, key, 1, default=default)
        for key, default in DEFAULT_CAPACITY.items()
    }
    if len(ck.problems) > start:
        return None

    low, high = values["eastbound_length_min"], values["eastbound_length_max"]
    if low > high:
        ck.problem(
            where,
            f"eastbound_length_min ({low}) is larger than eastbound_length_max ({high})",
        )
    if high > capacity["east_staging"]:
        ck.problem(
            where,
            f"eastbound_length_max ({high}) is larger than capacity east_staging "
            f"({capacity['east_staging']}) — the Eastbound manifest would not fit in East staging",
        )
    if len(ck.problems) > start:
        return None
    return Settings(**values, capacity=Capacity(**capacity))


# --- industries and spots -------------------------------------------------------


def _check_industries(ck: _Checker, raw: object) -> list[Industry]:
    if not isinstance(raw, list) or not raw:
        ck.problem("Configuration", "'industries' must list at least one industry")
        return []
    industries: list[Industry] = []
    ids_seen: dict[str, str] = {}
    names_seen: set[str] = set()
    spot_ids_seen: dict[str, str] = {}
    for number, item in enumerate(raw, 1):
        industry = _check_industry(ck, number, item, spot_ids_seen)
        if industry is None:
            continue
        if industry.id.casefold() in ids_seen:
            ck.problem(
                industry.name,
                f"id '{industry.id}' is already used by {ids_seen[industry.id.casefold()]}",
            )
            continue
        if industry.name.casefold() in names_seen:
            ck.problem(industry.name, "another industry already has this name")
            continue
        ids_seen[industry.id.casefold()] = industry.name
        names_seen.add(industry.name.casefold())
        industries.append(industry)
    return industries


def _check_industry(
    ck: _Checker, number: int, raw: object, spot_ids_seen: dict[str, str]
) -> Industry | None:
    fallback = f"Industry {number} in the list"
    if not isinstance(raw, dict):
        ck.problem(fallback, "must be a section with id, name and spots")
        return None
    label = _clean_text(raw.get("name")) or _clean_text(raw.get("id")) or fallback
    start = len(ck.problems)
    ck.unknown_fields(label, raw, INDUSTRY_FIELDS)
    industry_id = ck.text(label, raw, "id")
    industry_name = ck.text(label, raw, "name")

    spots_raw = raw.get("spots")
    spots: list[Spot] = []
    if not isinstance(spots_raw, list) or not spots_raw:
        ck.problem(label, "'spots' must list at least one spot")
    else:
        names_seen: set[str] = set()
        for spot_number, spot_raw in enumerate(spots_raw, 1):
            spot = _check_spot(
                ck, label, industry_id, industry_name, spot_number, spot_raw, spot_ids_seen
            )
            if spot is None:
                continue
            if spot.name.casefold() in names_seen:
                ck.problem(spot.label, "another spot in this industry already has this name")
                continue
            names_seen.add(spot.name.casefold())
            spots.append(spot)

    if len(ck.problems) > start:
        return None
    return Industry(id=industry_id, name=industry_name, spots=tuple(spots))


def _check_spot(
    ck: _Checker,
    industry_label: str,
    industry_id: str | None,
    industry_name: str | None,
    number: int,
    raw: object,
    spot_ids_seen: dict[str, str],
) -> Spot | None:
    fallback = f"{industry_label}, spot {number} in the list"
    if not isinstance(raw, dict):
        ck.problem(fallback, "must be a section with spot_id, name and requirement_mode")
        return None
    spot_label = _clean_text(raw.get("name")) or _clean_text(raw.get("spot_id"))
    label = f"{industry_label}, {spot_label}" if spot_label else fallback
    start = len(ck.problems)

    ck.unknown_fields(label, raw, SPOT_FIELDS)
    spot_id = ck.text(label, raw, "spot_id")
    name = ck.text(label, raw, "name")
    mode = ck.word(label, raw, "requirement_mode", REQUIREMENT_MODES)

    fixed = None
    possible: tuple[RandomRequirement, ...] = ()
    if mode == FIXED:
        for key in RANDOM_ONLY_FIELDS:
            if key in raw:
                ck.problem(label, f"'{key}' only applies to random spots")
        fixed = _check_fixed(ck, label, raw)
    elif mode == RANDOM:
        for key in FIXED_ONLY_FIELDS:
            if key in raw:
                ck.problem(
                    label, f"'{key}' belongs inside each possible requirement of a random spot"
                )
        possible = _check_possible_requirements(ck, label, raw)

    if spot_id is not None:
        key = spot_id.casefold()
        if key in spot_ids_seen:
            ck.problem(label, f"spot_id '{spot_id}' is already used by {spot_ids_seen[key]}")
        else:
            spot_ids_seen[key] = label

    if len(ck.problems) > start:
        return None
    return Spot(
        spot_id=spot_id,
        name=name,
        industry_id=industry_id,
        industry_name=industry_name,
        requirement_mode=mode,
        fixed=fixed,
        possible_requirements=possible,
    )


def _check_fixed(ck: _Checker, label: str, raw: dict) -> FixedRequirement | None:
    car_type = ck.text(label, raw, "car_type")
    direction = ck.word(label, raw, "direction", SPOT_DIRECTIONS)
    source = None
    pattern: tuple[str, ...] = ()
    disruption: float | None = 0.0
    if direction == INCOMING:
        for key in ("pattern", "disruption_chance"):
            if key in raw:
                ck.problem(label, f"'{key}' only applies to outgoing spots")
        source = ck.word(label, raw, "source", SIDES)
    elif direction == OUTGOING:
        if "source" in raw:
            ck.problem(label, "'source' only applies to incoming spots")
        pattern = _check_pattern(ck, label, raw)
        disruption = ck.chance(label, raw, "disruption_chance")
    base_days = ck.whole(label, raw, "base_processing_days", 1)
    delay = ck.chance(label, raw, "delay_chance", allow_one=False)
    idle = ck.whole(label, raw, "idle_days", 0, default=0)
    return FixedRequirement(
        car_type=car_type,
        direction=direction,
        source=source,
        pattern=pattern,
        disruption_chance=disruption,
        base_processing_days=base_days,
        delay_chance=delay,
        idle_days=idle,
    )


def _check_pattern(ck: _Checker, label: str, raw: dict) -> tuple[str, ...]:
    value = raw.get("pattern")
    if value is None:
        ck.problem(label, "missing 'pattern' — expected a list such as [East, East, West]")
        return ()
    if not isinstance(value, list) or not value:
        ck.problem(label, "'pattern' must be a list such as [East, East, West]")
        return ()
    pattern = []
    for item in value:
        side = match_word(item, SIDES)
        if side is None:
            ck.problem(label, f"pattern contains {_show(item)} — expected {either(SIDES)}")
        else:
            pattern.append(side)
    return tuple(pattern)


def _check_possible_requirements(
    ck: _Checker, label: str, raw: dict
) -> tuple[RandomRequirement, ...]:
    items = raw.get("possible_requirements")
    if not isinstance(items, list) or not items:
        ck.problem(label, "'possible_requirements' must list at least one requirement")
        return ()
    requirements = []
    for number, item in enumerate(items, 1):
        where = f"{label}, possible requirement {number}"
        if not isinstance(item, dict):
            ck.problem(where, "must be a section with car_type, direction and weights")
            continue
        ck.unknown_fields(where, item, REQUIREMENT_FIELDS)
        car_type = ck.text(where, item, "car_type")
        direction = ck.word(where, item, "direction", SPOT_DIRECTIONS)
        side_weights = None
        if direction == INCOMING:
            if "destination_weights" in item:
                ck.problem(where, "'destination_weights' only applies to outgoing requirements")
            side_weights = _check_side_weights(ck, where, item, "source_weights")
        elif direction == OUTGOING:
            if "source_weights" in item:
                ck.problem(where, "'source_weights' only applies to incoming requirements")
            side_weights = _check_side_weights(ck, where, item, "destination_weights")
        requirements.append(
            RandomRequirement(
                car_type=car_type,
                direction=direction,
                side_weights=side_weights,
                weight=ck.positive(where, item, "weight", default=1.0),
                base_processing_days=ck.whole(where, item, "base_processing_days", 1),
                delay_chance=ck.chance(where, item, "delay_chance", allow_one=False),
                idle_days=ck.whole(where, item, "idle_days", 0, default=0),
            )
        )
    return tuple(requirements)


def _check_side_weights(
    ck: _Checker, where: str, item: dict, key: str
) -> dict[str, float] | None:
    value = item.get(key)
    if value is None:
        ck.problem(where, f"missing '{key}' — for example {{East: 0.5, West: 0.5}}")
        return None
    if not isinstance(value, dict) or not value:
        ck.problem(where, f"'{key}' must be a section such as {{East: 0.5, West: 0.5}}")
        return None
    start = len(ck.problems)
    weights: dict[str, float] = {}
    for raw_side, weight in value.items():
        side = match_word(raw_side, SIDES)
        if side is None:
            ck.problem(where, f"'{key}' has {_show(raw_side)} — expected {either(SIDES)}")
        elif side in weights:
            ck.problem(where, f"'{key}' lists {side} twice")
        elif not _is_number(weight) or weight < 0:
            ck.problem(
                where, f"'{key}' for {side} must be a number of 0 or more (found {_show(weight)})"
            )
        else:
            weights[side] = float(weight)
    if len(ck.problems) > start:
        return None
    if sum(weights.values()) <= 0:
        ck.problem(where, f"'{key}' needs at least one weight above 0")
        return None
    return {side: weights.get(side, 0.0) for side in SIDES}
