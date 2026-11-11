"""Train planning (spec Sections 8 and 9): what each train carries today.

Runs at every day advance (and at the end of a cold start), after the spots
have advanced. It decides, for day D:

Today's demand (forecast.for_today), met in place-in-line order by
  1. a car already waiting on the Locals track assigned to that spot
     (yesterday's Eastbound Local block, or a car the local didn't deliver)
  2. outgoing spots: a held empty of the right type, longest-held first
  3. East-supplied: a car from the East loop -> the Westbound Local block
  West-supplied demand not met by 1-2 waits (a shortage; it self-corrects).

Tomorrow's demand (forecast.for_tomorrow, assuming today's local does all
its listed work), met in place-in-line order by
  1. a car waiting on the Locals track assigned to that spot, not used today
  2. outgoing spots: an empty that will be held on Locals tomorrow (held now
     and not used today, or pulled today from an incoming spot)
  3. West-supplied: a car from West staging -> the Eastbound Local block
  4. East-supplied: a car that will ride East today, so it is in the East
     loop tomorrow. First the Eastbound pick-up block (today's pulls headed
     East, and cars job B sends home East); otherwise a West staging car
     chosen as an "East-supply" continuing car on the Eastbound manifest.
  Assigning cars to tomorrow's East-supplied spots happens tomorrow, from
  whatever is then in the East loop; today only makes sure the cars are there.

Trains:
- Westbound manifest: every car in the East loop (closed set); continuing
  cars in random order, Local block at the rear.
- Eastbound manifest: length drawn from eastbound_length_min..max (counted
  leaving West staging), raised to the minimum (Local block + East-supply
  cars), lowered to what West staging holds; continuing cars in random
  order (East-supply cars + random filler), Local block at the rear.
- Local: today's set-outs (Locals-track cars + the Westbound Local block).
- Engines: manifest 2, or 3 when the longer of arriving and departing
  lengths reaches three_engines_from (or the train is overloaded); chosen at
  random from Manifest engines at that train's world plus Storage. The
  local gets 2 random Local-pool engines.
- Pick-up blocks are never left behind, except as a safeguard when West
  staging or the East loop would overflow: then the oldest pick-up cars go
  and the rest wait (spec Section 9).

Cars on the Locals track:
- assigned to a spot that still wants that car (type and load) -> wait for it
- otherwise released (confirmed 2026-11-11): an empty of a type some
  outgoing spot uses becomes a held empty; anything else goes home.
- a held empty unused for more than hold_days_on_locals day advances goes
  home. Cars going home are moved by job B (confirmed 2026-11-11) to the yard
  track toward their origin world.

`make_plan` is pure (config + records in, DayPlan out); `plan_day` reads the
database, plans, and writes the decisions. Call it inside a transaction.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from trainops import spots
from trainops import vocab as v
from trainops.config import Config, Spot
from trainops.db import Car, Database, Engine, SpotState
from trainops.forecast import Demand, Forecast, for_today, for_tomorrow, in_line

# How a demand is met (shown in notes and lists).
ALREADY_ON_LOCALS = "Already on Locals track"
HELD_EMPTY = "Held empty"
HELD_EMPTY_TOMORROW = "Held empty tomorrow"
WESTBOUND_BLOCK = "Westbound Local block"
EASTBOUND_BLOCK = "Eastbound Local block"
EASTBOUND_PICKUP = "Eastbound pickup"
EAST_SUPPLY = "East supply on Eastbound manifest"

LOCAL_ENGINES = 2


@dataclass(frozen=True)
class Supply:
    """How one demand is met; car_id None (and source None) = shortage."""

    demand: Demand
    car_id: int | None
    source: str | None


@dataclass(frozen=True)
class TrainPlan:
    train: str
    engine_ids: tuple[int, ...]
    car_ids: tuple[int, ...]  # head -> rear; the Local block is at the rear
    block_ids: tuple[int, ...] = ()  # the Local block (manifests)
    arriving: int = 0  # manifests: cars arriving at the yard
    departing: int = 0  # manifests: cars leaving the yard (predicted for the Eastbound)
    overload: bool = False  # an exception overload train


@dataclass(frozen=True)
class DayPlan:
    day: int
    today: Forecast
    tomorrow: Forecast
    today_supply: tuple[Supply, ...]
    tomorrow_supply: tuple[Supply, ...]
    westbound: TrainPlan
    eastbound: TrainPlan
    local: TrainPlan
    eastbound_draw: int  # the random length before the minimum and staging limits
    eastbound_minimum: int
    westbound_pickup: tuple[int, ...]  # job A: cars on the Westbound track that go
    eastbound_pickup: tuple[int, ...]  # job C, predicted
    assignments: dict[int, tuple[str, str]] = field(default_factory=dict)  # car -> (spot, load)
    released: tuple[int, ...] = ()  # cars on Locals that lose their assignment
    going_home: tuple[int, ...] = ()  # cars job B takes off the Locals track today
    local_has_work: bool = False
    notes: tuple[str, ...] = ()

    def train(self, name: str) -> TrainPlan:
        return {v.WESTBOUND_MANIFEST: self.westbound, v.EASTBOUND_MANIFEST: self.eastbound,
                v.LOCAL: self.local}[name]


# --- database wrapper ------------------------------------------------------------------


def plan_day(db: Database, config: Config, rng: random.Random) -> DayPlan:
    """Plan today's trains from the database and save the plan. Inside a transaction."""
    plan = make_plan(
        config, db.session().day, db.spot_states(), db.cars(), db.engines(), rng
    )
    apply_plan(db, plan)
    return plan


def apply_plan(db: Database, plan: DayPlan) -> None:
    for car in db.cars():
        if car.id in plan.assignments:
            spot_id, load = plan.assignments[car.id]
            db.update_car(car.id, assigned_spot=spot_id, load=load)
        elif car.id in plan.released:
            db.update_car(car.id, assigned_spot=None)
        elif car.loc_kind == v.AT_WORLD and (
            car.assigned_spot is not None or car.load != v.NOT_TRACKED
        ):
            db.update_car(car.id, assigned_spot=None, load=v.NOT_TRACKED)
    db.clear_consist_plans()
    for train in (plan.westbound, plan.eastbound, plan.local):
        db.set_consist_plan(
            train.train, engine_ids=list(train.engine_ids), car_ids=list(train.car_ids)
        )
    db.update_session(local_has_work=plan.local_has_work)


# --- the plan --------------------------------------------------------------------------


def make_plan(
    config: Config,
    day: int,
    states: dict[str, SpotState],
    cars: Iterable[Car],
    engines: Iterable[Engine],
    rng: random.Random,
) -> DayPlan:
    return _Planner(config, day, states, list(cars), list(engines), rng).plan()


def outgoing_types(config: Config) -> list[str]:
    """Car types some outgoing spot can use (empties of these are held on Locals)."""
    types = []
    for spot in config.spots:
        if spot.fixed:
            reqs = [spot.fixed] if spot.fixed.direction == v.OUTGOING else []
        else:
            reqs = [r for r in spot.possible_requirements if r.direction == v.OUTGOING]
        types += [r.car_type for r in reqs]
    return types


def engines_needed(arriving: int, departing: int, settings) -> int:
    longest = max(arriving, departing)
    if longest >= settings.three_engines_from or longest > settings.train_nominal_max:
        return 3
    return 2


class _Planner:
    def __init__(self, config, day, states, cars, engines, rng):
        self.config = config
        self.settings = config.settings
        self.day = day
        self.states = states
        self.cars = cars
        self.engines = engines
        self.rng = rng
        self.notes: list[str] = []
        self.assignments: dict[int, tuple[str, str]] = {}
        self.held_types = outgoing_types(config)

        self.east_loop = self._at(v.AT_WORLD, v.EAST_STAGING)
        self.west_pool = [c for c in self._at(v.AT_WORLD, v.WEST_STAGING) if not c.bad_order]
        self.at_spot = {c.loc_ref: c for c in cars if c.loc_kind == v.AT_SPOT}
        self.bad_order_spots = {s for s, c in self.at_spot.items() if c.bad_order}

    # ---- top level ----

    def plan(self) -> DayPlan:
        self._sort_locals_track()
        today = for_today(self.config, self.states, self.day, self.bad_order_spots)
        today_supply, wb_block = self._meet_today(today)
        served = {s.demand.spot_id for s in today_supply if s.car_id is not None}

        tomorrow = for_tomorrow(self.config, self.states, self.day, served, self.bad_order_spots)
        eb_pickup_all, wb_track_after = self._predict_pulls()
        tomorrow_supply, eb_block, east_supply = self._meet_tomorrow(tomorrow, eb_pickup_all)

        westbound, wb_pickup = self._westbound(wb_block)
        eastbound, draw, minimum, eb_pickup = self._eastbound(eb_block, east_supply, eb_pickup_all)
        westbound, eastbound = self._manifest_engines(westbound, eastbound)
        local = self._local(today_supply)

        for spot_id in tomorrow.not_drawn:
            self.notes.append(
                f"{self._label(spot_id)}: its next need isn't drawn yet, so no car "
                f"is planned for it tomorrow; it waits a day."
            )
        local_has_work = bool(local.car_ids) or any(
            s.state == v.READY_FOR_PICKUP for s in self.states.values()
        ) or bool(self.bad_order_spots)

        return DayPlan(
            day=self.day,
            today=today,
            tomorrow=tomorrow,
            today_supply=tuple(today_supply),
            tomorrow_supply=tuple(tomorrow_supply),
            westbound=westbound,
            eastbound=eastbound,
            local=local,
            eastbound_draw=draw,
            eastbound_minimum=minimum,
            westbound_pickup=tuple(c.id for c in wb_pickup),
            eastbound_pickup=tuple(c.id for c in eb_pickup),
            assignments=dict(self.assignments),
            released=tuple(c.id for c in self.released),
            going_home=tuple(c.id for c in self.going_home),
            local_has_work=local_has_work,
            notes=tuple(self.notes),
        )

    # ---- the Locals track ----

    def _sort_locals_track(self) -> None:
        """Split the Locals track into assigned, held empties and cars going home."""
        self.assigned: list[Car] = []
        self.held: list[Car] = []
        self.released: list[Car] = []
        self.going_home: list[Car] = []
        for car in self._at(v.AT_YARD, v.LOCALS_TRACK):
            if car.assigned_spot is not None:
                if self._still_wanted(car):
                    self.assigned.append(car)
                    continue
                self.released.append(car)
                self.notes.append(
                    f"{car.label} on the Locals track is no longer wanted at "
                    f"{self._label(car.assigned_spot)}."
                )
            if self._holdable(car) and car.days_held <= self.settings.hold_days_on_locals:
                self.held.append(car)
            else:
                self.going_home.append(car)

    def _still_wanted(self, car: Car) -> bool:
        spot = self.config.spots_by_id.get(car.assigned_spot)
        state = self.states.get(car.assigned_spot)
        if spot is None or state is None:
            return False
        wanted = [
            spots.need(spot, state),
            spots.upcoming_need(spot, state),
            spots.next_draw_need(spot, state),
        ]
        return any(
            n is not None and v.same_words(car.type, n.car_type) and car.load == _load_for(n.direction)
            for n in wanted
        )

    def _holdable(self, car: Car) -> bool:
        return car.load == v.EMPTY and any(v.same_words(car.type, t) for t in self.held_types)

    # ---- today ----

    def _meet_today(self, today: Forecast):
        supply = []
        block = []
        assigned = list(self.assigned)
        held = sorted(self.held, key=lambda c: (-c.days_held, c.seq or 0, c.id))
        east = list(self.east_loop)
        for demand in in_line(today.demands, self.rng):
            car = _take(assigned, lambda c: c.assigned_spot == demand.spot_id and self._matches(c, demand))
            source = ALREADY_ON_LOCALS
            if car is None and demand.direction == v.OUTGOING:
                car = _take(held, lambda c: v.same_words(c.type, demand.car_type))
                source = HELD_EMPTY
            if car is None and demand.side == v.EAST:
                car = self._take_random(east, demand)
                source = WESTBOUND_BLOCK
                if car is not None:
                    block.append(car)
            if car is None:
                supply.append(Supply(demand, None, None))
                self.notes.append(f"No car for {self._label(demand.spot_id)} today: "
                                  f"{_describe(demand)}.")
                continue
            if source != ALREADY_ON_LOCALS:
                self.assignments[car.id] = (demand.spot_id, demand.load)
            supply.append(Supply(demand, car.id, source))
        self.assigned_left = assigned  # still waiting after today
        self.held_left = held
        return supply, block

    # ---- what today's local and job B send where ----

    def _predict_pulls(self):
        """Predict the Eastbound pick-up block and tomorrow's held empties.

        Returns (cars for the Eastbound track by tonight, Westbound track cars
        added today). Cars pulled from industries get the record they will have
        after the pull (load, last loaded industry).
        """
        eastbound = self._at(v.AT_YARD, v.EASTBOUND_TRACK)
        westbound_added = []
        self.held_tomorrow = [
            c for c in self.held_left if c.days_held < self.settings.hold_days_on_locals
        ]
        for spot in self.config.spots:
            car = self.at_spot.get(spot.spot_id)
            state = self.states[spot.spot_id]
            if car is None:
                continue
            if car.bad_order:
                westbound_added.append(car)
                continue
            if state.state != v.READY_FOR_PICKUP:
                continue
            if spots.need(spot, state).direction == v.OUTGOING:
                pulled = replace(car, load=v.LOADED, last_loaded_industry=spot.industry_id)
                (eastbound if state.out_dest == v.EAST else westbound_added).append(pulled)
            else:
                pulled = replace(car, load=v.EMPTY)
                if self._holdable(pulled) and self.settings.hold_days_on_locals > 0:
                    self.held_tomorrow.append(pulled)
                elif pulled.origin_world == v.EAST_STAGING:
                    eastbound.append(pulled)
                else:
                    westbound_added.append(pulled)
        # Held empties reaching their limit today go home at tomorrow's job B, not today's.
        for car in self.going_home:
            (eastbound if car.origin_world == v.EAST_STAGING else westbound_added).append(car)
        return eastbound, westbound_added

    # ---- tomorrow ----

    def _meet_tomorrow(self, tomorrow: Forecast, eastbound_pickup: list[Car]):
        supply = []
        block = []
        east_supply = []
        assigned = list(self.assigned_left)
        held = sorted(self.held_tomorrow, key=lambda c: (-c.days_held, c.seq or 0, c.id))
        pickup = list(eastbound_pickup)
        self.west_left = list(self.west_pool)
        for demand in in_line(tomorrow.demands, self.rng):
            car = _take(assigned, lambda c: c.assigned_spot == demand.spot_id and self._matches(c, demand))
            source = ALREADY_ON_LOCALS
            if car is None and demand.direction == v.OUTGOING:
                car = _take(held, lambda c: v.same_words(c.type, demand.car_type))
                source = HELD_EMPTY_TOMORROW
            if car is None and demand.side == v.WEST:
                car = self._take_random(self.west_left, demand)
                source = EASTBOUND_BLOCK
                if car is not None:
                    block.append(car)
                    self.assignments[car.id] = (demand.spot_id, demand.load)
            if car is None and demand.side == v.EAST:
                car = _take(pickup, lambda c: self._fits(c, demand))
                source = EASTBOUND_PICKUP
                if car is None:
                    car = self._take_random(self.west_left, demand)
                    source = EAST_SUPPLY
                    if car is not None:
                        east_supply.append(car)
            if car is None:
                supply.append(Supply(demand, None, None))
                self.notes.append(f"No car for {self._label(demand.spot_id)} tomorrow: "
                                  f"{_describe(demand)}.")
                continue
            supply.append(Supply(demand, car.id, source))
        return supply, block, east_supply

    # ---- trains ----

    def _westbound(self, block: list[Car]):
        continuing = [c for c in self.east_loop if c not in block]
        self.rng.shuffle(continuing)
        block = _in_spot_order(block, self.assignments, self.config)
        cars = continuing + block
        arriving = len(cars)
        track = self._at(v.AT_YARD, v.WESTBOUND_TRACK)  # oldest first
        after_setout = arriving - len(block)
        room = self.settings.capacity.west_staging - len(self.west_pool) - after_setout
        pickup = track[: max(0, room)]
        if len(pickup) < len(track):
            self.notes.append(
                f"West staging is nearly full: {len(track) - len(pickup)} cars wait on the "
                f"Westbound track until tomorrow."
            )
        departing = after_setout + len(pickup)
        plan = TrainPlan(
            v.WESTBOUND_MANIFEST, (), tuple(c.id for c in cars), tuple(c.id for c in block),
            arriving, departing,
            max(arriving, departing) > self.settings.train_nominal_max,
        )
        return plan, pickup

    def _eastbound(self, block: list[Car], east_supply: list[Car], pickup_all: list[Car]):
        s = self.settings
        draw = self.rng.randint(s.eastbound_length_min, s.eastbound_length_max)
        minimum = len(block) + len(east_supply)
        length = min(max(draw, minimum), len(self.west_pool), s.capacity.east_staging)
        filler_count = max(0, length - minimum)
        filler = self.rng.sample(self.west_left, min(filler_count, len(self.west_left)))
        continuing = east_supply + filler
        self.rng.shuffle(continuing)
        block = _in_spot_order(block, self.assignments, self.config)
        cars = continuing + block
        if minimum > s.capacity.east_staging:
            self.notes.append(
                f"The Eastbound manifest needs {minimum} cars for the local and the East, "
                f"more than the East loop holds ({s.capacity.east_staging})."
            )
        arriving = len(cars)
        after_setout = arriving - len(block)
        room = s.capacity.east_staging - after_setout
        pickup = pickup_all[: max(0, room)]
        if len(pickup) < len(pickup_all):
            self.notes.append(
                f"The East loop is nearly full: {len(pickup_all) - len(pickup)} cars will "
                f"wait on the Eastbound track until tomorrow."
            )
        departing = after_setout + len(pickup)
        plan = TrainPlan(
            v.EASTBOUND_MANIFEST, (), tuple(c.id for c in cars), tuple(c.id for c in block),
            arriving, departing,
            max(arriving, departing) > s.train_nominal_max,
        )
        return plan, draw, minimum, pickup

    def _manifest_engines(self, westbound: TrainPlan, eastbound: TrainPlan):
        manifest = [e for e in self.engines if e.pool == v.POOL_MANIFEST]
        storage = [e for e in manifest if e.loc_kind == v.AT_STORAGE]
        chosen = []
        for train, world in ((westbound, v.EAST_STAGING), (eastbound, v.WEST_STAGING)):
            eligible = [e for e in manifest if e.loc_kind == v.AT_WORLD and e.loc_ref == world]
            eligible += [e for e in storage if e not in chosen]
            wanted = engines_needed(train.arriving, train.departing, self.settings)
            picked = self.rng.sample(eligible, min(wanted, len(eligible)))
            if len(picked) < wanted:
                self.notes.append(
                    f"The {train.train.lower()} needs {wanted} engines but only "
                    f"{len(picked)} are in {world} or Storage."
                )
            chosen += picked
            if train is westbound:
                westbound = replace(train, engine_ids=tuple(e.id for e in picked))
            else:
                eastbound = replace(train, engine_ids=tuple(e.id for e in picked))
        return westbound, eastbound

    def _local(self, today_supply: list[Supply]) -> TrainPlan:
        pool = [e for e in self.engines if e.pool == v.POOL_LOCAL]
        engines = self.rng.sample(pool, min(LOCAL_ENGINES, len(pool)))
        order = {s.spot_id: i for i, s in enumerate(self.config.spots)}
        setouts = sorted(
            (s for s in today_supply if s.car_id is not None),
            key=lambda s: order[s.demand.spot_id],
        )
        return TrainPlan(v.LOCAL, tuple(e.id for e in engines), tuple(s.car_id for s in setouts))

    # ---- helpers ----

    def _at(self, kind: str, ref: str) -> list[Car]:
        return sorted(
            (c for c in self.cars if c.loc_kind == kind and c.loc_ref == ref),
            key=lambda c: (c.seq or 0, c.id),
        )

    def _fits(self, car: Car, demand: Demand) -> bool:
        """A car can serve the demand: same type, and not loaded back to its shipper."""
        if not v.same_words(car.type, demand.car_type):
            return False
        industry = self.config.spot(demand.spot_id).industry_id
        return not (demand.direction == v.INCOMING and car.last_loaded_industry == industry)

    def _matches(self, car: Car, demand: Demand) -> bool:
        """An assigned car on Locals is the one for this demand: type and load."""
        return v.same_words(car.type, demand.car_type) and car.load == demand.load

    def _take_random(self, pool: list[Car], demand: Demand) -> Car | None:
        fitting = [c for c in pool if self._fits(c, demand)]
        if not fitting:
            return None
        car = self.rng.choice(fitting)
        pool.remove(car)
        return car

    def _label(self, spot_id: str) -> str:
        spot: Spot | None = self.config.spots_by_id.get(spot_id)
        return spot.label if spot else spot_id


def _take(pool: list[Car], test) -> Car | None:
    for car in pool:
        if test(car):
            pool.remove(car)
            return car
    return None


def _load_for(direction: str) -> str:
    return v.LOADED if direction == v.INCOMING else v.EMPTY


def _describe(demand: Demand) -> str:
    load = demand.load.lower()
    if demand.direction == v.INCOMING:
        return f"needs a {load} {demand.car_type} from the {demand.side}"
    return f"needs an {load} {demand.car_type} to load for the {demand.side}"


def _in_spot_order(block: list[Car], assignments, config: Config) -> list[Car]:
    """The Local block grouped by industry, in configuration order."""
    order = {s.spot_id: i for i, s in enumerate(config.spots)}
    return sorted(block, key=lambda c: order[assignments[c.id][0]])
