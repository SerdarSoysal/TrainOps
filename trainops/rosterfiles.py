"""Reading cars.csv and engines.csv (spec Section 16.5).

    cars.csv      mark,number,type,location        location: East staging | West staging
    engines.csv   mark,number,model,pool,location  pool: Local | Switcher | Manifest
                                                  location: Storage | East staging | West staging

Every column is required except an engine's model. Column names, locations
and pools are matched regardless of capitals; extra spaces are ignored;
reporting marks are stored in capitals. Problems are collected for the
whole file and reported with line numbers.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from trainops import vocab as v

CAR_COLUMNS = ("mark", "number", "type", "location")
ENGINE_COLUMNS = ("mark", "number", "model", "pool", "location")
ENGINE_REQUIRED = ("mark", "number", "pool", "location")
CAR_LOCATIONS = v.WORLDS
ENGINE_LOCATIONS = (v.STORAGE, v.EAST_STAGING, v.WEST_STAGING)

# Smallest engine roster that can always run a session (engine shortage is
# not modeled, so the roster must be ample).
MIN_ENGINES = {v.POOL_SWITCHER: 1, v.POOL_LOCAL: 2, v.POOL_MANIFEST: 6}
_MIN_ENGINE_REASON = {
    v.POOL_SWITCHER: "the yard switcher",
    v.POOL_LOCAL: "the local runs with 2",
    v.POOL_MANIFEST: "both manifests can need 3 each",
}


class RosterFileError(Exception):
    """One or both roster files have problems; `problems` lists them all."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        count = len(self.problems)
        head = (
            "The roster files have 1 problem:"
            if count == 1
            else f"The roster files have {count} problems:"
        )
        super().__init__("\n".join([head] + [f"  - {p}" for p in self.problems]))


@dataclass(frozen=True)
class CarRow:
    line: int
    mark: str
    number: str
    type: str
    location: str  # East staging | West staging

    @property
    def key(self) -> tuple[str, str]:
        return (self.mark.upper(), self.number)

    @property
    def label(self) -> str:
        return f"{self.mark} {self.number}"


@dataclass(frozen=True)
class EngineRow:
    line: int
    mark: str
    number: str
    model: str | None
    pool: str  # Local | Switcher | Manifest
    location: str  # Storage | East staging | West staging

    @property
    def key(self) -> tuple[str, str]:
        return (self.mark.upper(), self.number)

    @property
    def label(self) -> str:
        return f"{self.mark} {self.number}"


def read_cars(path: str | Path) -> tuple[list[CarRow], list[str]]:
    """Read cars.csv. Returns the good rows and a list of problems."""
    path = Path(path)
    rows, problems = _read_table(path, CAR_COLUMNS, CAR_COLUMNS)
    cars: list[CarRow] = []
    seen: dict[tuple[str, str], int] = {}
    for line, values in rows:
        where = f"{path.name}, line {line}"
        location = v.match_word(values["location"], CAR_LOCATIONS)
        if location is None:
            problems.append(
                f"{where}: location is '{values['location']}' — "
                f"expected {v.either(CAR_LOCATIONS)}"
            )
            continue
        car = CarRow(line, values["mark"].upper(), values["number"], values["type"], location)
        if car.key in seen:
            problems.append(f"{where}: {car.label} is already on line {seen[car.key]}")
            continue
        seen[car.key] = line
        cars.append(car)
    return cars, problems


def read_engines(path: str | Path) -> tuple[list[EngineRow], list[str]]:
    """Read engines.csv. Returns the good rows and a list of problems."""
    path = Path(path)
    rows, problems = _read_table(path, ENGINE_COLUMNS, ENGINE_REQUIRED)
    engines: list[EngineRow] = []
    seen: dict[tuple[str, str], int] = {}
    for line, values in rows:
        where = f"{path.name}, line {line}"
        pool = v.match_word(values["pool"], v.POOLS)
        location = v.match_word(values["location"], ENGINE_LOCATIONS)
        if pool is None:
            problems.append(f"{where}: pool is '{values['pool']}' — expected {v.either(v.POOLS)}")
        if location is None:
            problems.append(
                f"{where}: location is '{values['location']}' — "
                f"expected {v.either(ENGINE_LOCATIONS)}"
            )
        if pool is None or location is None:
            continue
        engine = EngineRow(
            line,
            values["mark"].upper(),
            values["number"],
            values["model"] or None,
            pool,
            location,
        )
        if engine.key in seen:
            problems.append(f"{where}: {engine.label} is already on line {seen[engine.key]}")
            continue
        seen[engine.key] = line
        engines.append(engine)
    return engines, problems


def engine_count_problems(pools: list[str], file_name: str = "engines.csv") -> list[str]:
    """Problems if a roster with these engine pools can't always run a session."""
    counts = Counter(pools)
    problems = []
    for pool, minimum in MIN_ENGINES.items():
        if counts[pool] < minimum:
            problems.append(
                f"{file_name}: needs at least {minimum} {pool.lower()} engine"
                f"{'s' if minimum > 1 else ''} ({_MIN_ENGINE_REASON[pool]}); "
                f"found {counts[pool]}"
            )
    return problems


def _read_table(
    path: Path, columns: tuple[str, ...], required: tuple[str, ...]
) -> tuple[list[tuple[int, dict[str, str]]], list[str]]:
    """Rows as (line number, {column: cleaned value}), plus problems."""
    name = path.name
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return [], [f"{name}: file not found ({path})"]
    except UnicodeDecodeError:
        return [], [
            f"{name}: some characters can't be read — save the file as 'CSV UTF-8' and try again"
        ]
    except OSError as e:
        return [], [f"{name}: can't read the file ({e.strerror})"]

    problems: list[str] = []
    rows: list[tuple[int, dict[str, str]]] = []
    header: list[str] | None = None
    reader = csv.reader(io.StringIO(text))
    for raw in reader:
        if not any(cell.strip() for cell in raw):
            continue  # blank line
        line = reader.line_num
        if header is None:
            header = [" ".join(cell.split()).casefold() for cell in raw]
            missing = [c for c in columns if c not in header]
            unknown = [c for c in header if c not in columns]
            doubled = sorted({c for c in header if header.count(c) > 1})
            if missing:
                problems.append(
                    f"{name}: missing column{'s' if len(missing) > 1 else ''} "
                    f"{v.both(missing)} — the first line must be {','.join(columns)}"
                )
            for column in unknown:
                problems.append(f"{name}: unknown column '{column}'")
            for column in doubled:
                problems.append(f"{name}: column '{column}' appears twice")
            if problems:
                return [], problems
            continue
        if len(raw) != len(header):
            problems.append(
                f"{name}, line {line}: has {len(raw)} values, expected {len(header)} "
                f"({','.join(header)})"
            )
            continue
        values = {col: " ".join(cell.split()) for col, cell in zip(header, raw)}
        empty = [c for c in required if not values[c]]
        if empty:
            problems.append(f"{name}, line {line}: {v.both(empty)} {'is' if len(empty) == 1 else 'are'} empty")
            continue
        rows.append((line, values))

    if header is None:
        problems.append(f"{name}: the file is empty")
    return rows, problems
