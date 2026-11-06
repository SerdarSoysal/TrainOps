# Digital Train Operations — Project Checkpoint

*Checkpoint date: 2026-07-13. This document captures all decisions made so far so a new conversation can pick up where this one left off. If resuming, upload this file first. This supersedes the 2026-07-09 checkpoint.*

## 1. Project Overview & Philosophy

The goal is to digitize **operations** on an N scale model railroad — not automate physical train movement (no DCC/dispatcher automation is in scope here). Traditionally, model railroaders use manual car cards and waybills to plan work sessions. This project replaces that manual paperwork process with software that generates the day's work automatically, driven by industry demand — similar in spirit to real railroads responding to shipper demand.

**Key philosophical decision:** cars are **not tracked individually**. There is no roster of specific numbered cars. Industries only care about *car type* (boxcar, hopper, flatcar, etc.), not which specific physical car fills a slot. This is a deliberate simplification and is the main reason existing tools like JMRI Operations (which is built around tracking specific rolling stock by road name/number) were ruled out in favor of a custom build. A spreadsheet-based approach was also explicitly ruled out.

**Planned physical layer (deferred for now):** Arduino/ESP32-based push buttons and small LCD displays at each industry, used to physically confirm job completion, plus a "next day" button to advance the session. The user has prior experience with Arduino (built a linear actuator-driven train elevator) and has used Claude Code for Python projects before. **This entire physical/hardware layer remains explicitly deferred** until the software/data model is fully specified — see Section 10.

## 2. Layout Structure

- **3 industries** to start (extensible design, not hardcoded to 3)
- Each industry currently uses one of: flatcar, boxcar, hopper (car types not needed by industries — e.g. tank cars, reefers, coal hoppers — never route to Local; they only move East↔West as through traffic)
- **The yard is a loop** and contains (at least) 3 physical sorting tracks:
  - **Local** — pool of cars destined for/coming from industries
  - **East** — sorting track for cars logically bound east
  - **West** — sorting track for cars logically bound west
- **Staging is a single stub-ended yard (3 tracks planned)** that represents the *entirety* of "the rest of the world" beyond this junction — both the eastern and western connections, collapsed into one physical place. See Section 6 for the full reasoning.
- **Passing sidings** exist between the yard and staging (count still TBD) — meaning a departing train can leave the yard even if all staging tracks are occupied, since it can duck into a siding and let an arriving train pass.

## 3. Daily Operating Sequence (high-level)

1. Train(s) arrive at the yard from "East" or "West" (logically) and are **classified/sorted** into tracks — OR pass through unchanged if a through train (see Section 7).
2. Cars sorted into **Local** enter the pool available to service industries.
3. The **local job** does the switching at all industries needing service that day — pickups and spots are combined into a single visit per industry (Section 5).
4. Cars pulled from industries (now loaded, per their outgoing pattern/destination) go to the East or West sorting track.
5. Yard engines rebuild outbound trains from the East/West sorting tracks (combining continuing cars from breakdown arrivals with newly-loaded cars from the local job).
6. Train(s) depart the yard toward staging (physically identical regardless of logical direction — see Section 6).

See Section 7 for the concrete v1 daily train schedule template.

## 4. Industry / Spot Data Model

An **Industry** is just a name plus a list of **Spots**. All industry-specific behavior lives at the spot level — there is no special-cased "industry type." This was validated by working through a real "transfer facility" example: it turned out to need **no special handling at all** — it's just an ordinary industry where some spots are `fixed` (e.g. a tanker spot that only ever receives tankers from a fixed source) and one spot is `random` (a misc spot that can receive/ship various car types in variable directions). See Section 9 for the full example.

### Spot schema (current, final)

```json
{
  "spot_id": "...",
  "requirement_mode": "fixed | random",

  // --- FIXED MODE fields ---
  "car_type": "...",
  "direction": "incoming | outgoing",
  "source": "E | W",                   // if direction = incoming
  "pattern": ["E", "E", "W"],          // if direction = outgoing — ordered, repeating destination list
  "position": 0,                        // RUNTIME STATE — pointer into pattern, persists across sessions
  "disruption_chance": 0.0,             // per-completion chance to flip the scheduled pattern destination
  "base_processing_days": 2,            // FIXED MODE ONLY — see note below
  "delay_chance": 0.0,                  // FIXED MODE ONLY — rerolled every day while processing
  "cooldown_days": 0,                   // FIXED MODE ONLY — fixed value, no variance

  // --- RANDOM MODE fields ---
  "possible_requirements": [
    {
      "car_type": "...",
      "direction": "incoming | outgoing",
      "source_weights": {"E": 0.5, "W": 0.5},        // if incoming — fresh weighted roll EVERY draw, no persisted position
      "destination_weights": {"E": 0.5, "W": 0.5},   // if outgoing — fresh weighted roll EVERY draw, no persisted position
      "weight": 3,                                    // likelihood this requirement gets drawn vs. other entries
      "base_processing_days": 2,                      // lives HERE for random mode, not at spot level
      "delay_chance": 0.1,                             // lives HERE for random mode
      "cooldown_days": 0                               // lives HERE for random mode
    }
  ]
}
```

**Key rule confirmed this session:** `pattern`/`position` is a **fixed-spot-only** concept, representing a deterministic (if lopsided) repeating rhythm. Random-mode spots never get a repeating pattern for direction — every time a random requirement is drawn (including being drawn again later after other requirements were drawn in between), its E/W split is rolled fresh from `source_weights`/`destination_weights`, with no memory across draws. This sidesteps the "does position persist per-requirement-type" dilemma entirely, since randomness is the intended behavior for these spots, not something a reset could break.

**Also confirmed this session:** `base_processing_days`, `delay_chance`, and `cooldown_days` belong to **whichever entity fully determines the job** — for fixed spots that's the spot itself; for random spots that's the individual `possible_requirements` entry (since different draws, e.g. unloading a tanker vs. loading a boxcar, can realistically take different amounts of time and have different cooldown needs). Spot-level versions of these three fields only apply when `requirement_mode = fixed`.

### Spot state machine (unchanged)

```
EMPTY_AWAITING_CAR → PROCESSING (countdown, daily delay reroll)
                    → READY_FOR_PICKUP
                    → [pulled]
                    → COOLDOWN (fixed days, skipped if cooldown_days = 0)
                    → EMPTY_AWAITING_CAR  (cycle repeats; for random spots, a new requirement is drawn here)
```

- **INCOMING spot**: needs a *loaded* car of `car_type` arriving from `source` (fixed) or a source rolled per `source_weights` (random) to fill it. When pulled, the car is now *empty* and returns to the Local pool.
- **OUTGOING spot**: needs an *empty* car of `car_type` from the Local pool to fill it. When pulled, the car is now *loaded* and routed per `pattern`/`position` (fixed) or a destination rolled per `destination_weights` (random).

## 5. Key Rules & Mechanics (industry/spot level)

- **Outgoing pattern/position** (fixed spots only): `position` advances by one (with wraparound) **every completion, unconditionally** — including when a disruption flips the outcome. Disruptions are self-correcting, not compounding.
- **Delay mechanic**: rerolled **every day** a spot is in PROCESSING. Delays can stack arbitrarily — intentional, considered realistic, no cap.
- **Cooldown mechanic**: fixed value, no variance. Models industries with genuinely slow turnover as distinct from same-day-resupply industries (`cooldown_days = 0`).
- **Shortage/contention rule**: spots serviced **oldest-waiting-first**; random tiebreak among equally-old spots. An unserviceable spot just stays in `EMPTY_AWAITING_CAR` and rolls forward — no special backlog flag needed.
- **Same-day pickup + resupply**: one visit to an industry (the "local job") both pulls `READY_FOR_PICKUP` spots and resupplies `EMPTY_AWAITING_CAR` spots in the same job, provided Local classification happens before the local job runs each day.
- **Job granularity (partial decision)**: one job per industry per day. Physical button/press granularity is still deferred (Section 10).
- **Transfer facility**: not a special case — just an industry with a mix of fixed spots (e.g. tanker-only, centerbeam-only) and one or more random spots (e.g. a misc spot handling boxcar/flatcar/hopper in variable directions). See Section 9 for the worked example.

## 6. Yard & Staging Model

**The layout represents:** a junction on a busy East–West mainline. Trains arrive/depart daily in both directions; local industries are served from the yard; some trains get broken down (splitting off Local-bound cars from continuing traffic) while others are pure through-trains (engine swap only, no classification).

**The physical reality driving this model:** there is only **one** physical connection to "the rest of the world" — a 3-track stub-ended staging yard. There is no separate physical East staging and West staging. Attempting to make the single staging area physically represent two different places (e.g. via a loop-back trick) was considered and explicitly rejected as forcing believability.

**Resolution (confirmed this session):**
- **East and West are purely logical/software labels**, not physical destinations. Every train, regardless of its logical direction, physically runs to/from the same stub staging.
- **The yard (loop) does have real, separate physical sorting tracks for East and West** — these are used to organize/build outbound trains before departure, even though both tracks ultimately feed the same physical staging connection.
- **Staging capacity (3 tracks) does NOT create scheduling pressure**, because passing sidings between the yard and staging mean a departing train can leave even if staging is fully occupied (it ducks into a siding to let an arriving train pass). So arrivals and departures are fully independent events from a scheduling standpoint.
- **Staging is ephemeral/notional (Option B, confirmed)** — it holds **no persistent state** between sessions. The software does not track "what's sitting in staging" as a pool or reconcile it over time. Each day, arrivals and departures are generated as independent, self-contained events: an arrival is simply declared ("today's eastbound arrival contains X cars of Y types"), and a departure is simply dissolved once it runs into staging. Nothing is remembered as "waiting to become a future arrival." This was explicitly chosen as more realistic than a stateful staging model, given passing sidings remove the capacity-pressure argument for tracking it.

## 7. Daily Train Schedule (v1)

**Confirmed for v1: a single, fixed, predefined daily schedule that repeats every operating day** (configurable by the user editing the template, but not varied automatically session-to-session). Example template discussed (order matters and encodes real dependencies):

```
1. Westbound through train arrives from East, continues on (engine swap only)
2. Eastbound train arrives from West, gets broken down
3. Westbound train arrives from East, gets broken down
4. Local job runs
5. Eastbound through train arrives from West, continues on (engine swap only)
6. Yard engines rebuild eastbound and westbound outbound trains
7. Westbound train departs (= #3's continuing cars + local job's west-tagged outgoing cars)
8. Eastbound train departs (= #2's continuing cars + local job's east-tagged outgoing cars)
```

**Dependency graph revealed by this example** (a preview of the "job sequencing" topic, item 2 in Section 11):
- Through-train events (#1, #5) have **no dependencies** — engine swap only, no pool interaction.
- The **local job (#4) depends on** both breakdown arrivals (#2, #3) having already classified their Local-bound cars.
- **Departures (#7, #8) depend on** both their corresponding breakdown arrival's continuing cars AND the local job's newly-loaded outgoing cars.

**Flagged for v2 (not part of v1 scope):**
- Randomizing train order and/or count per day (rather than one fixed repeating template)
- Weekday vs. weekend (or other cyclical) schedule variants

## 8. Demand-Driven Arrival/Departure Logic

**Confirmed this session:** the Local-vs-continuing split on a breakdown arrival is **demand-driven**, not a fixed ratio or random range.

**Mechanism:**
- Every incoming spot's `source` field (fixed spots) already ties it to a specific arrival direction. A westbound-from-East arrival can only satisfy incoming spots whose relevant source is East; an eastbound-from-West arrival only satisfies West-sourced spots. (For random-mode spots, this is handled via whichever source got rolled for that requirement — see Section 4.)
- When a breakdown arrival happens, the software tallies aggregate demand: the sum, per car type, of every currently-eligible incoming spot (state = `EMPTY_AWAITING_CAR`, not in cooldown) whose source matches this arrival's origin. That exact tally becomes the Local-tagged portion of the arrival's manifest.
- **Everything else in that arrival is "continuing" traffic** — these cars are through traffic that no industry ever asks about, so their specific car types don't need to be demand-tracked at all; they can be abstract/filler (e.g. the job card just says "14 through cars," no type detail required).

**Confirmed: outgoing-spot demand does NOT feed back into arrival generation for v1.** Outgoing spots draw only from whatever has already accumulated in the Local pool (from incoming spots being unloaded). If that pool runs dry, a genuine shortage on the outgoing side is an acceptable, expected outcome — the software does not inject extra empty cars into arrivals to relieve outgoing-side shortfalls. (This "demand-aware yard" idea — proactively restocking Local based on outgoing pressure too — is explicitly flagged as a v2 idea, not v1.)

**Confirmed: train size flexes with demand.** An arrival's total car count = (however many cars the Local demand calculation calls for) + (a separately configured number/range of through/continuing cars). This was chosen over a fully fixed car count per template event.

**Still open / deferred by user (to think about further):** the exact configuration of the through/continuing car count — fixed number vs. configurable random range — has not yet been decided.

## 9. Industry/Spot Config Examples

**Simple fixed outgoing spot, always East:**
```json
{"spot_id": "brewery_out_1", "car_type": "boxcar", "direction": "outgoing", "pattern": ["E"], "position": 0, "disruption_chance": 0.0}
```

**Fixed outgoing spot, every third car West:**
```json
{"spot_id": "brewery_out_2", "car_type": "boxcar", "direction": "outgoing", "pattern": ["E", "E", "W"], "position": 0, "disruption_chance": 0.0}
```

**Slow-turnover spot with cooldown (weekly hopper example):**
```json
{"spot_id": "brewery_hopper_1", "car_type": "hopper", "direction": "incoming", "source": "E", "base_processing_days": 2, "delay_chance": 0.0, "cooldown_days": 3}
```

**Transfer facility — worked real-world example (3 spots, only 1 actually random):**
```json
// Spot 1 — tanker spot, ONLY tankers, ALWAYS from West — an ordinary FIXED spot
{"spot_id": "transfer_tanker", "requirement_mode": "fixed", "car_type": "tanker", "direction": "incoming", "source": "W", "base_processing_days": 2, "delay_chance": 0.0, "cooldown_days": 0}

// Spot 2 — centerbeam spot, ONLY centerbeam, ALWAYS from East — an ordinary FIXED spot
{"spot_id": "transfer_centerbeam", "requirement_mode": "fixed", "car_type": "centerbeam", "direction": "incoming", "source": "E", "base_processing_days": 2, "delay_chance": 0.0, "cooldown_days": 0}

// Spot 3 — misc spot, boxcar/flatcar/hopper, variable direction/source/destination — the genuinely RANDOM spot
{
  "spot_id": "transfer_misc",
  "requirement_mode": "random",
  "possible_requirements": [
    {"car_type": "boxcar",  "direction": "incoming", "source_weights": {"E": 0.5, "W": 0.5}, "weight": 3, "base_processing_days": 2, "delay_chance": 0.1, "cooldown_days": 0},
    {"car_type": "boxcar",  "direction": "outgoing", "destination_weights": {"E": 0.5, "W": 0.5}, "weight": 3, "base_processing_days": 2, "delay_chance": 0.1, "cooldown_days": 0},
    {"car_type": "flatcar", "direction": "incoming", "source_weights": {"E": 0.3, "W": 0.7}, "weight": 2, "base_processing_days": 3, "delay_chance": 0.1, "cooldown_days": 0},
    {"car_type": "hopper",  "direction": "outgoing", "destination_weights": {"E": 0.5, "W": 0.5}, "weight": 2, "base_processing_days": 3, "delay_chance": 0.1, "cooldown_days": 1}
  ]
}
```

## 10. Technology Direction (proposed, still not confirmed/final)

Unchanged from prior checkpoint — still parked until the software/data model is fully specified:

- Central "brain": Raspberry Pi or PC running the job generator, SQLite likely sufficient.
- Hardware nodes: ESP32-based (WiFi built in) at each industry, push button + optional I2C LCD.
- Communication: MQTT (e.g. Mosquitto broker) for pub/sub between nodes and the brain.
- "Next day" button: another MQTT node, or wired directly if physically close.
- Possible companion web dashboard for full job list detail beyond what an LCD can show.

## 11. Explicitly Deferred / Future (v2) Items

- **All physical button/LCD/hardware design decisions**, including job granularity at the button level (one button per industry vs. per spot vs. start/complete pairs) — deferred until the software model is fully specified.
- **Randomizing the daily train schedule** (order and/or count of trains) rather than one fixed repeating template — flagged for v2.
- **Weekday vs. weekend (or other cyclical) schedule variants** — flagged for v2.
- **Demand-aware arrival injection** — proactively adding extra empty cars to arrivals to relieve outgoing-side shortages in Local — flagged for v2; v1 allows genuine outgoing shortages.
- **Through/continuing car count configuration** (fixed vs. random range) — not yet decided, user wants to think about it further.
- **Transfer facility open detail from prior checkpoint is now RESOLVED** (see Section 4) — no longer open.

## 12. Plan Going Forward (agreed order)

1. ~~Yard-side logic (incl. inbound train handling)~~ — **substantially complete.** Remaining loose end: through/continuing car count configuration (Section 8).
2. **Engine assignment logic** — how the system recommends which engine(s) to use per job; simple free-pool assignment vs. tracking engine location/home turf over time. **Not yet started.**
3. **Job sequencing/dependencies** — whether jobs need to respect ordering (we already found a concrete real dependency graph in Section 7 while designing the daily schedule — this topic is partially pre-answered by that example, but hasn't been formally addressed as its own topic yet).
4. Physical button/display design — deferred, see Section 11.
