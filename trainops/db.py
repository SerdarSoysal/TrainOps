"""The state database (spec Sections 16.2 and 16.3).

SQLite through the standard sqlite3 module, no ORM. Five tables:
session (one row), car, engine, spot_state, consist_plan.

Every change happens inside `Database.transaction()`, and each signal or
edit is exactly one transaction: either all of its changes are saved or
none are. Writing outside a transaction is refused.

Stored values are plain words (see `vocab`); spots are stored by their
internal spot_id and shown by name elsewhere. Done flags are 0 or 1.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from pathlib import Path

from trainops import vocab as v

SCHEMA_VERSION = 2  # 2: session columns renamed to the switcher job names


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


_SIDES = _sql_list(v.SIDES)
_WORLDS = _sql_list(v.WORLDS)

SCHEMA = f"""
CREATE TABLE session (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    day               INTEGER NOT NULL CHECK (day >= 1),
    west_chore_done   INTEGER NOT NULL DEFAULT 0 CHECK (west_chore_done IN (0, 1)),
    east_chore_done   INTEGER NOT NULL DEFAULT 0 CHECK (east_chore_done IN (0, 1)),
    switch_westbound_done        INTEGER NOT NULL DEFAULT 0 CHECK (switch_westbound_done IN (0, 1)),
    local_back        INTEGER NOT NULL DEFAULT 0 CHECK (local_back IN (0, 1)),
    local_return_done        INTEGER NOT NULL DEFAULT 0 CHECK (local_return_done IN (0, 1)),
    switch_eastbound_done        INTEGER NOT NULL DEFAULT 0 CHECK (switch_eastbound_done IN (0, 1)),
    local_has_work    INTEGER NOT NULL DEFAULT 0 CHECK (local_has_work IN (0, 1))
);

CREATE TABLE car (
    id                   INTEGER PRIMARY KEY,
    mark                 TEXT NOT NULL COLLATE NOCASE,
    number               TEXT NOT NULL,
    type                 TEXT NOT NULL,
    loc_kind             TEXT NOT NULL,
    loc_ref              TEXT NOT NULL,
    seq                  INTEGER,
    load                 TEXT NOT NULL DEFAULT '{v.NOT_TRACKED}'
                         CHECK (load IN ({_sql_list(v.LOADS)})),
    last_loaded_industry TEXT,
    origin_world         TEXT NOT NULL CHECK (origin_world IN ({_WORLDS})),
    assigned_spot        TEXT,
    dest_world           TEXT CHECK (dest_world IS NULL OR dest_world IN ({_WORLDS})),
    days_held            INTEGER NOT NULL DEFAULT 0 CHECK (days_held >= 0),
    bad_order            INTEGER NOT NULL DEFAULT 0 CHECK (bad_order IN (0, 1)),
    UNIQUE (mark, number),
    CHECK (
        (loc_kind = '{v.AT_WORLD}' AND loc_ref IN ({_WORLDS}) AND seq IS NULL)
        OR (loc_kind = '{v.AT_YARD}' AND loc_ref IN ({_sql_list(v.YARD_TRACKS)})
            AND seq IS NOT NULL)
        OR (loc_kind = '{v.AT_SPOT}' AND seq IS NULL)
        OR (loc_kind = '{v.AT_TRAIN}' AND loc_ref IN ({_sql_list(v.TRAINS)})
            AND seq IS NOT NULL)
    )
);

-- A spot holds one car.
CREATE UNIQUE INDEX one_car_per_spot ON car (loc_ref) WHERE loc_kind = '{v.AT_SPOT}';

CREATE TABLE engine (
    id        INTEGER PRIMARY KEY,
    mark      TEXT NOT NULL COLLATE NOCASE,
    number    TEXT NOT NULL,
    model     TEXT,
    pool      TEXT NOT NULL CHECK (pool IN ({_sql_list(v.POOLS)})),
    loc_kind  TEXT NOT NULL,
    loc_ref   TEXT NOT NULL,
    seq       INTEGER,
    UNIQUE (mark, number),
    CHECK (
        (loc_kind = '{v.AT_WORLD}' AND loc_ref IN ({_WORLDS}) AND seq IS NULL)
        OR (loc_kind = '{v.AT_TRAIN}' AND loc_ref IN ({_sql_list(v.TRAINS)})
            AND seq IS NOT NULL)
        OR (loc_kind = '{v.AT_STORAGE}' AND loc_ref = '{v.STORAGE}' AND seq IS NULL)
    )
);

CREATE TABLE spot_state (
    spot_id                 TEXT PRIMARY KEY,
    industry_id             TEXT NOT NULL,  -- as at the last cold start
    identity                TEXT NOT NULL,  -- mode, car type(s), direction(s) at the last cold start
    state                  TEXT NOT NULL CHECK (state IN ({_sql_list(v.SPOT_STATES)})),
    days_left               INTEGER CHECK (days_left IS NULL OR days_left >= 0),
    position                INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    requirement_number      INTEGER CHECK (requirement_number IS NULL OR requirement_number >= 1),
    requirement_side        TEXT CHECK (requirement_side IS NULL OR requirement_side IN ({_SIDES})),
    out_dest                TEXT CHECK (out_dest IS NULL OR out_dest IN ({_SIDES})),
    waiting_since_day       INTEGER,
    next_delay              INTEGER CHECK (next_delay IS NULL OR next_delay IN (0, 1)),
    next_requirement_number INTEGER
        CHECK (next_requirement_number IS NULL OR next_requirement_number >= 1),
    next_requirement_side   TEXT
        CHECK (next_requirement_side IS NULL OR next_requirement_side IN ({_SIDES}))
);

CREATE TABLE consist_plan (
    train      TEXT NOT NULL CHECK (train IN ({_sql_list(v.TRAINS)})),
    seq        INTEGER NOT NULL CHECK (seq >= 1),
    car_id     INTEGER REFERENCES car (id),
    engine_id  INTEGER REFERENCES engine (id),
    PRIMARY KEY (train, seq),
    CHECK ((car_id IS NULL) <> (engine_id IS NULL))
);

INSERT INTO session (id, day) VALUES (1, 1);
"""


class DatabaseError(Exception):
    """A plain-language problem with the database or a requested change."""


# --- rows ------------------------------------------------------------------


@dataclass(frozen=True)
class Session:
    day: int
    west_chore_done: bool
    east_chore_done: bool
    switch_westbound_done: bool
    local_back: bool
    local_return_done: bool
    switch_eastbound_done: bool
    local_has_work: bool


@dataclass(frozen=True)
class Car:
    id: int
    mark: str
    number: str
    type: str
    loc_kind: str
    loc_ref: str
    seq: int | None
    load: str
    last_loaded_industry: str | None  # industry id
    origin_world: str  # East staging | West staging
    assigned_spot: str | None  # spot_id
    dest_world: str | None  # East staging | West staging
    days_held: int
    bad_order: bool  # retired while at a spot: local pulls it, it leaves at West staging

    @property
    def label(self) -> str:
        return f"{self.mark} {self.number}"


@dataclass(frozen=True)
class Engine:
    id: int
    mark: str
    number: str
    model: str | None
    pool: str
    loc_kind: str
    loc_ref: str
    seq: int | None

    @property
    def label(self) -> str:
        return f"{self.mark} {self.number}"


@dataclass(frozen=True)
class SpotState:
    spot_id: str
    state: str
    # Recorded at cold start; a later config that changes them needs a cold start.
    industry_id: str = field(kw_only=True)
    identity: str = field(kw_only=True)
    days_left: int | None = None
    position: int = 0
    requirement_number: int | None = None  # random spots: which possible requirement (1 = first)
    requirement_side: str | None = None  # random spots: rolled East | West
    out_dest: str | None = None  # outgoing: East | West, fixed at ready for pickup
    waiting_since_day: int | None = None
    next_delay: bool | None = None  # day-ahead delay roll
    next_requirement_number: int | None = None  # day-ahead random draw
    next_requirement_side: str | None = None

    @classmethod
    def fresh(cls, spot_id: str, day: int, *, industry_id: str, identity: str) -> SpotState:
        """A spot at cold start: empty and waiting for a car from today."""
        return cls(
            spot_id=spot_id,
            state=v.AWAITING_CAR,
            waiting_since_day=day,
            industry_id=industry_id,
            identity=identity,
        )


@dataclass(frozen=True)
class PlanEntry:
    train: str
    seq: int
    car_id: int | None
    engine_id: int | None


_SESSION_FLAGS = tuple(f.name for f in fields(Session) if f.name != "day")
_CAR_FIELDS = tuple(f.name for f in fields(Car) if f.name != "id")
_ENGINE_FIELDS = tuple(f.name for f in fields(Engine) if f.name != "id")
_SPOT_FIELDS = tuple(f.name for f in fields(SpotState))
_BOOL_SPOT_FIELDS = ("next_delay",)


def _row_to(cls, row: sqlite3.Row):
    return cls(**{key: row[key] for key in row.keys()})


# Car columns in the dataclass's field order, so a row converts by position (fast:
# the simulator reads the car table thousands of times).
_CAR_SELECT = ", ".join(f.name for f in fields(Car))
assert fields(Car)[-1].name == "bad_order"


def _car_from_row(row: sqlite3.Row) -> Car:
    return Car(*row[:-1], bool(row[-1]))


def _spot_from_row(row: sqlite3.Row) -> SpotState:
    data = {key: row[key] for key in row.keys()}
    for key in _BOOL_SPOT_FIELDS:
        if data[key] is not None:
            data[key] = bool(data[key])
    return SpotState(**data)


# --- the database ------------------------------------------------------------


class Database:
    """One open state database. Use `Database.open(path)`."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._in_transaction = False

    @classmethod
    def open(cls, path: str | Path, *, discard_other_version: bool = False) -> Database:
        """Open the database, creating it if it doesn't exist yet.

        Pass ":memory:" for a throwaway database (tests). A database made by a
        different program version is refused, unless discard_other_version is
        set (cold start only), in which case it is deleted and made afresh.
        """
        try:
            return cls._open(path)
        except DatabaseError:
            if not discard_other_version or str(path) == ":memory:":
                raise
        Path(path).unlink()
        return cls._open(path)

    @classmethod
    def _open(cls, path: str | Path) -> Database:
        conn = sqlite3.connect(str(path), autocommit=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        db = cls(conn)
        try:
            db._ensure_schema()
        except DatabaseError:
            conn.close()
            raise
        return db

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _ensure_schema(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        has_tables = self._conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
        if version == 0 and not has_tables:
            # One statement at a time inside our own transaction
            # (executescript would commit on its own).
            with self.transaction():
                for statement in _statements(SCHEMA):
                    self._conn.execute(statement)
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return
        raise DatabaseError(
            f"The database was made by a different version of TrainOps "
            f"(database format {version}, this program uses format {SCHEMA_VERSION}). "
            f"Start fresh with a cold start."
        )

    # --- transactions ---

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        """All changes inside are saved together, or not at all if an error occurs."""
        if self._in_transaction:
            raise RuntimeError("a transaction is already open; they can't be nested")
        self._conn.execute("BEGIN IMMEDIATE")
        self._in_transaction = True
        try:
            yield self
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")
        finally:
            self._in_transaction = False

    def _write(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        if not self._in_transaction:
            raise RuntimeError("changes must be made inside db.transaction()")
        return self._conn.execute(sql, params)

    def _read(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    # --- session ---

    def session(self) -> Session:
        row = self._read("SELECT * FROM session WHERE id = 1")[0]
        return Session(
            day=row["day"], **{flag: bool(row[flag]) for flag in _SESSION_FLAGS}
        )

    def update_session(self, **changes: int | bool) -> Session:
        unknown = set(changes) - {"day", *_SESSION_FLAGS}
        if unknown:
            raise ValueError(f"unknown session field(s): {', '.join(sorted(unknown))}")
        if changes:
            values = {k: int(val) for k, val in changes.items()}
            assignments = ", ".join(f"{k} = :{k}" for k in values)
            self._write(f"UPDATE session SET {assignments} WHERE id = 1", values)
        return self.session()

    # --- cars ---

    def cars(self) -> list[Car]:
        return [_car_from_row(r) for r in self._read(f"SELECT {_CAR_SELECT} FROM car ORDER BY id")]

    def car(self, car_id: int) -> Car:
        rows = self._read(f"SELECT {_CAR_SELECT} FROM car WHERE id = ?", (car_id,))
        if not rows:
            raise DatabaseError(f"no car with id {car_id}")
        return _car_from_row(rows[0])

    def find_car(self, mark: str, number: str) -> Car | None:
        """Find a car by mark and number; capitals in the mark don't matter."""
        rows = self._read(
            f"SELECT {_CAR_SELECT} FROM car WHERE mark = ? AND number = ?", (mark.strip(), number.strip())
        )
        return _car_from_row(rows[0]) if rows else None

    def cars_at(self, loc_kind: str, loc_ref: str) -> list[Car]:
        """Cars at one place, in order (seq, oldest or head first)."""
        rows = self._read(
            f"SELECT {_CAR_SELECT} FROM car WHERE loc_kind = ? AND loc_ref = ? ORDER BY seq, id",
            (loc_kind, loc_ref),
        )
        return [_car_from_row(r) for r in rows]

    def add_car(
        self,
        *,
        mark: str,
        number: str,
        type: str,
        loc_kind: str,
        loc_ref: str,
        origin_world: str,
        seq: int | None = None,
        load: str = v.NOT_TRACKED,
        last_loaded_industry: str | None = None,
        assigned_spot: str | None = None,
        dest_world: str | None = None,
        days_held: int = 0,
        bad_order: bool = False,
    ) -> Car:
        if self.find_car(mark, number) is not None:
            raise DatabaseError(f"car {mark} {number} is already in the roster")
        values = dict(
            mark=mark,
            number=number,
            type=type,
            loc_kind=loc_kind,
            loc_ref=loc_ref,
            seq=seq,
            load=load,
            last_loaded_industry=last_loaded_industry,
            origin_world=origin_world,
            assigned_spot=assigned_spot,
            dest_world=dest_world,
            days_held=days_held,
            bad_order=int(bad_order),
        )
        cursor = self._insert("car", values)
        return self.car(cursor.lastrowid)

    def update_car(self, car_id: int, **changes) -> Car:
        self._update("car", _CAR_FIELDS, car_id, changes)
        return self.car(car_id)

    def remove_car(self, car_id: int) -> None:
        self.car(car_id)  # raises if missing
        self._write("DELETE FROM car WHERE id = ?", (car_id,))

    # --- engines ---

    def engines(self) -> list[Engine]:
        return [_row_to(Engine, r) for r in self._read("SELECT * FROM engine ORDER BY id")]

    def engine(self, engine_id: int) -> Engine:
        rows = self._read("SELECT * FROM engine WHERE id = ?", (engine_id,))
        if not rows:
            raise DatabaseError(f"no engine with id {engine_id}")
        return _row_to(Engine, rows[0])

    def find_engine(self, mark: str, number: str) -> Engine | None:
        rows = self._read(
            "SELECT * FROM engine WHERE mark = ? AND number = ?", (mark.strip(), number.strip())
        )
        return _row_to(Engine, rows[0]) if rows else None

    def engines_at(self, loc_kind: str, loc_ref: str) -> list[Engine]:
        rows = self._read(
            "SELECT * FROM engine WHERE loc_kind = ? AND loc_ref = ? ORDER BY seq, id",
            (loc_kind, loc_ref),
        )
        return [_row_to(Engine, r) for r in rows]

    def add_engine(
        self,
        *,
        mark: str,
        number: str,
        pool: str,
        loc_kind: str,
        loc_ref: str,
        model: str | None = None,
        seq: int | None = None,
    ) -> Engine:
        if self.find_engine(mark, number) is not None:
            raise DatabaseError(f"engine {mark} {number} is already in the roster")
        values = dict(
            mark=mark,
            number=number,
            model=model,
            pool=pool,
            loc_kind=loc_kind,
            loc_ref=loc_ref,
            seq=seq,
        )
        cursor = self._insert("engine", values)
        return self.engine(cursor.lastrowid)

    def update_engine(self, engine_id: int, **changes) -> Engine:
        self._update("engine", _ENGINE_FIELDS, engine_id, changes)
        return self.engine(engine_id)

    def remove_engine(self, engine_id: int) -> None:
        self.engine(engine_id)  # raises if missing
        self._write("DELETE FROM engine WHERE id = ?", (engine_id,))

    # --- spot states ---

    def spot_states(self) -> dict[str, SpotState]:
        rows = self._read("SELECT * FROM spot_state ORDER BY spot_id")
        return {r["spot_id"]: _spot_from_row(r) for r in rows}

    def spot_state(self, spot_id: str) -> SpotState | None:
        rows = self._read("SELECT * FROM spot_state WHERE spot_id = ?", (spot_id,))
        return _spot_from_row(rows[0]) if rows else None

    def put_spot_state(self, state: SpotState) -> None:
        """Save a spot's whole state, replacing what was there."""
        values = {name: getattr(state, name) for name in _SPOT_FIELDS}
        for key in _BOOL_SPOT_FIELDS:
            if values[key] is not None:
                values[key] = int(values[key])
        columns = ", ".join(values)
        placeholders = ", ".join(f":{k}" for k in values)
        self._write(
            f"INSERT OR REPLACE INTO spot_state ({columns}) VALUES ({placeholders})", values
        )

    # --- consist plan ---

    def consist_plan(self, train: str) -> list[PlanEntry]:
        rows = self._read(
            "SELECT * FROM consist_plan WHERE train = ? ORDER BY seq", (train,)
        )
        return [_row_to(PlanEntry, r) for r in rows]

    def set_consist_plan(
        self, train: str, *, engine_ids: list[int], car_ids: list[int]
    ) -> list[PlanEntry]:
        """Replace a train's plan: engines lead first, then cars head to rear."""
        self._write("DELETE FROM consist_plan WHERE train = ?", (train,))
        seq = 0
        for engine_id in engine_ids:
            seq += 1
            self._write(
                "INSERT INTO consist_plan (train, seq, engine_id) VALUES (?, ?, ?)",
                (train, seq, engine_id),
            )
        for car_id in car_ids:
            seq += 1
            self._write(
                "INSERT INTO consist_plan (train, seq, car_id) VALUES (?, ?, ?)",
                (train, seq, car_id),
            )
        return self.consist_plan(train)

    def clear_consist_plans(self) -> None:
        self._write("DELETE FROM consist_plan")

    def remove_from_consist_plans(
        self, *, car_id: int | None = None, engine_id: int | None = None
    ) -> None:
        """Take one car or engine out of any plan; the rest close up in order."""
        column, row_id = ("car_id", car_id) if car_id is not None else ("engine_id", engine_id)
        rows = self._read(f"SELECT train FROM consist_plan WHERE {column} = ?", (row_id,))
        self._write(f"DELETE FROM consist_plan WHERE {column} = ?", (row_id,))
        for train in {r["train"] for r in rows}:
            entries = self.consist_plan(train)
            for new_seq, entry in enumerate(entries, 1):
                if entry.seq != new_seq:
                    self._write(
                        "UPDATE consist_plan SET seq = ? WHERE train = ? AND seq = ?",
                        (new_seq, train, entry.seq),
                    )

    # --- everything ---

    def clear_all(self) -> None:
        """Empty every table and start again at day 1 (cold start)."""
        for table in ("consist_plan", "car", "engine", "spot_state"):
            self._write(f"DELETE FROM {table}")
        self.update_session(
            day=1, **{flag: False for flag in _SESSION_FLAGS}
        )

    # --- helpers ---

    def _insert(self, table: str, values: dict) -> sqlite3.Cursor:
        columns = ", ".join(values)
        placeholders = ", ".join(f":{k}" for k in values)
        return self._write(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", values)

    def _update(self, table: str, allowed: tuple[str, ...], row_id: int, changes: dict) -> None:
        unknown = set(changes) - set(allowed)
        if unknown:
            raise ValueError(f"unknown {table} field(s): {', '.join(sorted(unknown))}")
        if not changes:
            return
        assignments = ", ".join(f"{k} = :{k}" for k in changes)
        cursor = self._write(
            f"UPDATE {table} SET {assignments} WHERE id = :_id", {**changes, "_id": row_id}
        )
        if cursor.rowcount == 0:
            raise DatabaseError(f"no {table} with id {row_id}")


def _statements(script: str) -> list[str]:
    """Split the schema script into single statements (none contain ';' inside)."""
    return [s.strip() for s in script.split(";") if s.strip()]
