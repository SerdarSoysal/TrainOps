"""Simulator (development step 10): play many days automatically.

Runs the real program (cold start, signals, planning) on an in-memory
database, doing every job the way an operator would. The local can skip
some of its moves at random, and cars at spots can be retired as Bad order
at random, to exercise the recovery rules.

After every signal it checks that the railroad still makes sense:
- no car lost or duplicated (only Bad order cars leave, at West staging)
- the East loop is a closed set: the westbound manifest takes exactly the
  cars the eastbound manifest left there
- West staging and the East loop stay within their capacities
- a spot holds a car exactly while it is processing or ready for pickup
- cars in the worlds are untracked unless planned for a Local block
- every car on the Locals track is assigned to a spot or a held empty
At the end, every spot must have received cars.

It reports train lengths, overload trains, how long spots wait, how often
held empties are reused, and how full the yard tracks get: the figures for
tuning a real industry configuration.
"""

from __future__ import annotations

import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from trainops import vocab as v
from trainops.coldstart import cold_start
from trainops.config import Config
from trainops.db import Database
from trainops.planning import engines_needed, outgoing_types
from trainops.roster import retire_car
from trainops.planning import west_train
from trainops.signals import handle, set_chore_mode
from trainops.worklists import actions
from trainops.yardwork import local_return, switch_eastbound, switch_westbound


class InvariantBroken(Exception):
    """Something the railroad must never do happened; the message says what."""


@dataclass
class Report:
    days: int
    seed: int
    skip_chance: float
    bad_order_chance: float
    chore_mode: str = v.CHORE_FULL  # Full, Quick or Mixed
    quick_chores: Counter = field(default_factory=Counter)  # world -> days with a quick chore
    cars: int = 0
    engines: int = 0
    signals: int = 0
    broken: str | None = None  # the first invariant broken, if any
    westbound_lengths: list[int] = field(default_factory=list)  # leaving the yard
    eastbound_lengths: list[int] = field(default_factory=list)
    eastbound_leaving_west: list[int] = field(default_factory=list)
    overloads: Counter = field(default_factory=Counter)  # train -> days
    three_engines: Counter = field(default_factory=Counter)
    setouts: Counter = field(default_factory=Counter)  # spot -> cars set out
    waits: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    short_days: Counter = field(default_factory=Counter)  # spot -> days with no car
    pulls: int = 0
    skipped_moves: int = 0
    local_skipped_days: int = 0
    held_reused: int = 0
    held_sent_home: int = 0
    bad_orders: int = 0
    yard_most: Counter = field(default_factory=Counter)  # track -> most cars at once
    notes: Counter = field(default_factory=Counter)

    @property
    def never_served(self) -> list[str]:
        return [s for s, n in self.setouts.items() if n == 0]


def simulate(
    config: Config,
    cars_path: str | Path,
    engines_path: str | Path,
    days: int,
    seed: int = 1,
    skip_chance: float = 0.0,
    bad_order_chance: float = 0.0,
    chore_mode: str | None = None,
) -> Report:
    """chore_mode: Full, Quick, Mixed (changed at random each day) or None (config's)."""
    db = Database.open(":memory:")
    mode = (chore_mode or config.settings.chore_mode).capitalize()
    try:
        return _Sim(db, config, seed, skip_chance, bad_order_chance, mode).run(
            cars_path, engines_path, days)
    finally:
        db.close()


class _Sim:
    def __init__(self, db, config, seed, skip_chance, bad_order_chance,
                 chore_mode=v.CHORE_FULL):
        self.db = db
        self.config = config
        self.rng = random.Random(seed)
        self.report = Report(0, seed, skip_chance, bad_order_chance, chore_mode)
        self.report.setouts.update({s.spot_id: 0 for s in config.spots})
        self.held: set[int] = set()
        self.east_set: set[int] | None = None
        self.labels = {s.label: s.spot_id for s in config.spots}

    # ---- the run ----

    def run(self, cars_path, engines_path, days) -> Report:
        r = self.report
        cold_start(self.db, self.config, cars_path, engines_path, rng=self.rng)
        if r.chore_mode in v.CHORE_MODES:
            set_chore_mode(self.db, r.chore_mode)
        r.cars, r.engines = len(self.db.cars()), len(self.db.engines())
        self.car_ids = {c.id for c in self.db.cars()}
        try:
            self._check()
            for _ in range(days):
                self._day()
                r.days += 1
            r.never_served  # computed on demand
        except InvariantBroken as problem:
            r.broken = f"Day {self.db.session().day}: {problem}"
        return r

    def _day(self) -> None:
        db, r = self.db, self.report
        if self.rng.random() < self.report.bad_order_chance:
            self._retire_one()

        if r.chore_mode not in v.CHORE_MODES:  # Mixed: the toggle changes at random
            set_chore_mode(db, self.rng.choice(v.CHORE_MODES))
        self.east_set = {c.id for c in db.cars_at(v.AT_WORLD, v.EAST_STAGING)}
        session = db.session()
        west_before = west_train(db.cars())
        east_before = [c for c in db.cars_at(v.AT_WORLD, v.EAST_STAGING) if c.seq is not None]
        self._send(v.WEST_CHORE_DONE)
        self._send(v.EAST_CHORE_DONE)
        if session.west_chore_mode == v.CHORE_QUICK:
            r.quick_chores[v.WEST_STAGING] += 1
            self._quick_check(v.EASTBOUND_MANIFEST, west_before)
        if session.east_chore_mode == v.CHORE_QUICK:
            r.quick_chores[v.EAST_STAGING] += 1
            self._quick_check(v.WESTBOUND_MANIFEST, east_before)
        built = {c.id for c in db.cars_at(v.AT_TRAIN, v.WESTBOUND_MANIFEST)}
        if built != self.east_set:
            raise InvariantBroken("the westbound manifest is not exactly the East loop's cars")
        self._engines_check(v.WESTBOUND_MANIFEST, switch_westbound)
        eb_leaving = len(db.cars_at(v.AT_TRAIN, v.EASTBOUND_MANIFEST))
        r.eastbound_leaving_west.append(eb_leaving)

        # The westbound reaches West staging at a random point after Switch westbound.
        self.westbound_home_at = self.rng.randrange(6)
        self._send(v.WESTBOUND_IN_YARD)
        job = switch_westbound(db, self.config)
        r.westbound_lengths.append(job.length_after)
        r.overloads[v.WESTBOUND_MANIFEST] += job.overload
        self._send(v.SWITCH_WESTBOUND_DONE)
        self._westbound_home(0)

        if db.session().local_back:
            r.local_skipped_days += 1
        else:
            self._run_local()
            self._send(v.LOCAL_BACK)
        self._westbound_home(1)
        if not db.session().local_return_done:
            for move in local_return(db, self.config):
                if move.reason == "empty, held for reuse":
                    self.held.add(move.car.id)
                elif move.car.loc_kind == v.AT_YARD and move.car.id in self.held:
                    self.held.discard(move.car.id)
                    r.held_sent_home += 1
            self._send(v.LOCAL_RETURN_DONE)
        self._westbound_home(2)

        self._send(v.EASTBOUND_IN_YARD)
        self._westbound_home(3)
        self._engines_check(v.EASTBOUND_MANIFEST, switch_eastbound)
        job = switch_eastbound(db, self.config)
        r.eastbound_lengths.append(job.length_after)
        r.overloads[v.EASTBOUND_MANIFEST] += job.overload
        leaving = {c.id for c in db.cars_at(v.AT_TRAIN, v.EASTBOUND_MANIFEST)}
        leaving = (leaving - {c.id for c in job.cut}) | {c.id for c in job.pickup}
        self._send(v.SWITCH_EASTBOUND_DONE)
        self._westbound_home(4)
        self._send(v.EASTBOUND_IN_EAST_STAGING)
        if {c.id for c in db.cars_at(v.AT_WORLD, v.EAST_STAGING)} != leaving:
            raise InvariantBroken("the East loop doesn't hold exactly the eastbound's cars")
        self._westbound_home(5)

        notes = self._send(v.SESSION_COMPLETE)
        for note in notes[1:]:
            if note.startswith("No car for ") and " today: " in note:
                label = note[len("No car for "):note.index(" today: ")]
                r.short_days[self.labels.get(label, label)] += 1
            else:
                r.notes[note.split(":")[0]] += 1

    def _quick_check(self, train: str, before: list) -> None:
        """A quick chore keeps yesterday's order for the reused cars; Local block at the rear."""
        cars = self.db.cars_at(v.AT_TRAIN, train)
        ids = {c.id for c in before}
        reused = [c.id for c in cars if c.id in ids and not c.assigned_spot]
        if reused != [c.id for c in before if c.id in set(reused)]:
            raise InvariantBroken(f"the {train.lower()} (quick chore) changed the order "
                                  f"of yesterday's cars")
        flags = [bool(c.assigned_spot) for c in cars]
        if flags != sorted(flags):
            raise InvariantBroken(f"the {train.lower()}'s Local block is not at the rear")
        if train == v.WESTBOUND_MANIFEST and len(reused) + sum(flags) != len(cars):
            raise InvariantBroken("the westbound (quick chore) gained cars")

    def _westbound_home(self, stage: int) -> None:
        if stage == self.westbound_home_at:
            self._send(v.WESTBOUND_IN_WEST_STAGING)

    def _run_local(self) -> None:
        db, r = self.db, self.report
        skipped: set[tuple[str, str]] = set()
        while True:
            todo = [a for a in actions(db, self.config)
                    if a.spot_id and (a.signal, a.spot_id) not in skipped]
            if not todo:
                return
            act = todo[0]
            if self.rng.random() < r.skip_chance:
                skipped.add((act.signal, act.spot_id))
                r.skipped_moves += 1
                continue
            if act.signal == v.SET_OUT_DONE:
                state = db.spot_state(act.spot_id)
                r.waits[act.spot_id].append(db.session().day - state.waiting_since_day)
                car = next(c for c in db.cars_at(v.AT_TRAIN, v.LOCAL)
                           if c.assigned_spot == act.spot_id)
                if car.id in self.held:
                    self.held.discard(car.id)
                    r.held_reused += 1
                r.setouts[act.spot_id] += 1
            else:
                r.pulls += 1
            self._send(act.signal, act.spot_id)

    def _retire_one(self) -> None:
        at_spots = [c for c in self.db.cars() if c.loc_kind == v.AT_SPOT and not c.bad_order]
        if at_spots:
            with self.db.transaction():
                retire_car(self.db, self.config, self.rng.choice(at_spots))
            self.report.bad_orders += 1

    # ---- signals and checks ----

    def _send(self, signal: str, spot_id: str | None = None) -> list[str]:
        notes = handle(self.db, self.config, signal, spot_id, self.rng)
        self.report.signals += 1
        self._check()
        return notes

    def _engines_check(self, train: str, job_of) -> None:
        engines = len(self.db.engines_at(v.AT_TRAIN, train))
        job = job_of(self.db, self.config)
        arriving = len(self.db.cars_at(v.AT_TRAIN, train))
        wanted = engines_needed(arriving, job.length_after, self.config.settings)
        # The plan used predicted lengths; allow the prediction to differ by one engine.
        if abs(engines - wanted) > 1 or engines < 2:
            raise InvariantBroken(f"the {train.lower()} has {engines} engines")
        self.report.three_engines[train] += engines == 3

    def _check(self) -> None:
        db, config = self.db, self.config
        cars = db.cars()
        ids = {c.id for c in cars}
        if not ids <= self.car_ids:
            raise InvariantBroken("a car appeared that isn't in the roster")
        for gone in self.car_ids - ids:
            self.car_ids.discard(gone)  # only Bad order cars may leave, checked below
            if not self._was_bad_order(gone):
                raise InvariantBroken(f"car {gone} disappeared")

        states = db.spot_states()
        at_spot = Counter(c.loc_ref for c in cars if c.loc_kind == v.AT_SPOT)
        for spot_id, state in states.items():
            busy = state.state in (v.PROCESSING, v.READY_FOR_PICKUP)
            if at_spot[spot_id] != (1 if busy else 0):
                raise InvariantBroken(
                    f"{config.spot(spot_id).label} is {state.state.lower()} "
                    f"with {at_spot[spot_id]} cars")

        cap = config.settings.capacity
        places = Counter((c.loc_kind, c.loc_ref) for c in cars)
        east = places[(v.AT_WORLD, v.EAST_STAGING)]
        west = places[(v.AT_WORLD, v.WEST_STAGING)]
        if not db.session().eastbound_in_yard:  # still in West staging, or may be
            west += places[(v.AT_TRAIN, v.EASTBOUND_MANIFEST)]
        if east > cap.east_staging:
            raise InvariantBroken(f"East loop holds {east} cars (capacity {cap.east_staging})")
        if west > cap.west_staging:
            raise InvariantBroken(f"West staging holds {west} cars (capacity {cap.west_staging})")

        planned = {e.car_id for t in v.TRAINS for e in db.consist_plan(t)}
        held_types = outgoing_types(config)
        for c in cars:
            if c.loc_kind == v.AT_WORLD and (c.load != v.NOT_TRACKED or c.assigned_spot) \
                    and c.id not in planned:
                raise InvariantBroken(f"{c.label} in {c.loc_ref} is tracked but not planned")
            if c.loc_kind == v.AT_YARD and c.loc_ref == v.LOCALS_TRACK and not c.assigned_spot:
                holdable = c.load == v.EMPTY and any(v.same_words(c.type, t) for t in held_types)
                if not holdable:
                    raise InvariantBroken(f"{c.label} is on the Locals track for no reason")
        for track in v.YARD_TRACKS:
            n = places[(v.AT_YARD, track)]
            self.report.yard_most[track] = max(self.report.yard_most[track], n)
        self._bad_order_ids = {c.id for c in cars if c.bad_order}

    def _was_bad_order(self, car_id: int) -> bool:
        return car_id in getattr(self, "_bad_order_ids", set())


# --- the report ------------------------------------------------------------------------


def format_report(report: Report, config: Config) -> str:
    r = report
    lines = [
        f"TrainOps simulation: {r.days} days, seed {r.seed}",
        f"  {r.cars} cars, {r.engines} engines, {len(config.spots)} spots; "
        f"local moves skipped at random: {r.skip_chance:.0%}; "
        f"Bad order chance per day: {r.bad_order_chance:.0%}",
        f"  Chores: {r.chore_mode.lower()}; quick chores on {r.quick_chores[v.WEST_STAGING]} "
        f"days in West staging, {r.quick_chores[v.EAST_STAGING]} in the East loop",
        "",
    ]
    if r.broken:
        lines += [f"PROBLEM — {r.broken}", ""]
    else:
        lines += [f"Every check held after all {r.signals} signals.", ""]

    def spread(values: list[int]) -> str:
        if not values:
            return "none"
        return (f"shortest {min(values)}, average {statistics.mean(values):.1f}, "
                f"longest {max(values)}")

    days = max(r.days, 1)
    lines += [
        "Trains (cars leaving the yard)",
        f"  Westbound manifest: {spread(r.westbound_lengths)}; overload trains on "
        f"{r.overloads[v.WESTBOUND_MANIFEST]} days ({r.overloads[v.WESTBOUND_MANIFEST] / days:.0%}); "
        f"3 engines on {r.three_engines[v.WESTBOUND_MANIFEST]} days",
        f"  Eastbound manifest: {spread(r.eastbound_lengths)}; overload trains on "
        f"{r.overloads[v.EASTBOUND_MANIFEST]} days ({r.overloads[v.EASTBOUND_MANIFEST] / days:.0%}); "
        f"3 engines on {r.three_engines[v.EASTBOUND_MANIFEST]} days",
        f"  Eastbound leaving West staging: {spread(r.eastbound_leaving_west)}",
        "",
        "Local",
        f"  Cars set out per day: {sum(r.setouts.values()) / days:.1f}; "
        f"pulled per day: {r.pulls / days:.1f}; no local work on {r.local_skipped_days} days",
    ]
    if r.skip_chance:
        lines.append(f"  Moves skipped on purpose: {r.skipped_moves}")
    if r.bad_order_chance:
        lines.append(f"  Cars retired as Bad order: {r.bad_orders}")
    lines += [
        f"  Held empties: {r.held_reused} reused, {r.held_sent_home} sent home unused",
        "",
        "Spots (wait = days from wanting a car to getting one)",
    ]
    rows = [("Spot", "Cars", "Average wait", "Longest wait", "Days short")]
    for spot in config.spots:
        waits = r.waits.get(spot.spot_id, [])
        rows.append((
            spot.label,
            str(r.setouts[spot.spot_id]),
            f"{statistics.mean(waits):.1f}" if waits else "-",
            str(max(waits)) if waits else "-",
            str(r.short_days[spot.spot_id]),
        ))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        lines.append("  " + row[0].ljust(widths[0]) + "".join(
            "  " + cell.rjust(w) for cell, w in zip(row[1:], widths[1:])))
    lines += [
        "",
        f"Yard tracks, most cars at once (capacity {config.settings.capacity.yard_track}): "
        + ", ".join(f"{t} {r.yard_most[t]}" for t in v.YARD_TRACKS),
    ]
    over = [t for t in v.YARD_TRACKS if r.yard_most[t] > config.settings.capacity.yard_track]
    if over:
        lines.append(f"  Over capacity: {v.both(over)}")
    if r.never_served:
        lines.append("Never got a car: " + v.both(config.spot(s).label for s in r.never_served))
    if r.notes:
        lines += ["", "Other notes (how often)"]
        lines += [f"  {n:>4}  {text}" for text, n in r.notes.most_common(10)]
    return "\n".join(lines)
