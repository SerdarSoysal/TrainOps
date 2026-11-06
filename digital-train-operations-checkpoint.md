# Digital Train Operations — Project Checkpoint

*Checkpoint date: 2026-07-09. This document captures all decisions made so far so a new conversation can pick up where this one left off. If resuming, upload this file first.*

## 1. Project Overview & Philosophy

The goal is to digitize **operations** on an N scale model railroad — not automate physical train movement (no DCC/dispatcher automation is in scope here). Traditionally, model railroaders use manual car cards and waybills to plan work sessions. This project replaces that manual paperwork process with software that generates the day's work automatically, driven by industry demand — similar in spirit to real railroads responding to shipper demand.

**Key philosophical decision:** cars are **not tracked individually**. There is no roster of specific numbered cars. Industries only care about *car type* (boxcar, hopper, flatcar, etc.), not which specific physical car fills a slot. This is a deliberate simplification and is the main reason existing tools like JMRI Operations (which is built around tracking specific rolling stock by road name/number) were ruled out in favor of a custom build. A spreadsheet-based approach was also explicitly ruled out.

**Planned physical layer (deferred for now):** Arduino/ESP32-based push buttons and small LCD displays at each industry, used to physically confirm job completion, plus a "next day" button to advance the session. The user has prior experience with Arduino (built a linear actuator-driven train elevator) and has used Claude Code for Python projects before. **This entire physical/hardware layer has been explicitly deferred** until the software/data model is fully specified — see Section 8.

## 2. Layout Structure

- **3 industries** to start (extensible design, not hardcoded to 3)
- Each industry currently uses one of: flatcar, boxcar, hopper (car types not needed by industries — e.g. tank cars, reefers, coal hoppers — never route to Local; they only move East↔West as through traffic)
- **Yard has 3 tracks:**
  - **Local** — pool of cars destined for/coming from industries
  - **East** — through track toward the eastern connection/division
  - **West** — through track toward the western connection/division

## 3. Daily Operating Sequence

1. Train(s) arrive at the yard from East and/or West and are **classified/sorted** into tracks.
2. Cars sorted into **Local** enter the pool available to service industries.
3. The **local job** does the switching at all industries needing service that day — pickups and spots are combined into a single visit per industry (see Section 6).
4. Cars pulled from industries go to a **sorting track**, then get split into East-bound and West-bound groups.
5. Train(s) depart the yard toward East and/or West.

This full loop (steps 1, 4-5 especially) is **not yet designed in detail** — it's the next planned topic (Section 9, item 1).

## 4. Industry / Spot Data Model

An **Industry** is just a name plus a list of **Spots**. All industry-specific behavior lives at the spot level — there is no special-cased "industry type"; even the unusual "transfer facility" industry (Section 6) is expressed through the same spot schema.

### Spot schema

```json
{
  "spot_id": "...",
  "requirement_mode": "fixed | random",

  "car_type": "...",              // if requirement_mode = fixed
  "direction": "incoming | outgoing",  // if requirement_mode = fixed
  "source": "E | W",              // if direction = incoming
  "pattern": ["E", "E", "W"],     // if direction = outgoing (ordered destination list)
  "position": 0,                  // RUNTIME STATE, not config — pointer into pattern

  "possible_requirements": [      // if requirement_mode = random
    {"car_type": "...", "direction": "...", "weight": 5, "...": "additional fields as above"}
  ],

  "base_processing_days": 2,
  "delay_chance": 0.0,            // rerolled EVERY DAY while processing (see Section 6)
  "disruption_chance": 0.0,       // per-completion chance to flip the scheduled pattern destination
  "cooldown_days": 0              // fixed value, no variance — idle period after pickup before spot re-enters service pool
}
```

**Important distinction:** `pattern` (and `possible_requirements`) is static configuration written once. `position`, current occupancy/processing state, and days-remaining counters are runtime state that persists across sessions and must never be reset by a config reload.

### Spot state machine

```
EMPTY_AWAITING_CAR → PROCESSING (countdown, daily delay reroll)
                    → READY_FOR_PICKUP
                    → [pulled]
                    → COOLDOWN (fixed days, skipped if cooldown_days = 0)
                    → EMPTY_AWAITING_CAR  (cycle repeats)
```

- **INCOMING spot**: needs a *loaded* car of `car_type` arriving from `source` (E or W) to fill it. When pulled (after processing), the car is now *empty* and returns to the Local pool as available supply.
- **OUTGOING spot**: needs an *empty* car of `car_type` from the Local pool to fill it. When pulled (after processing), the car is now *loaded* and is routed to a destination per `pattern`/`position` (with possible `disruption_chance` flip), heading to the East or West sorting track.

This creates a natural supply loop: incoming spots produce empties into the Local pool; outgoing spots consume those empties and produce loaded cars for departure.

## 5. Key Rules & Mechanics

- **Outgoing pattern/position**: `pattern` is an ordered list (e.g. `["E","E","W"]`). `position` advances by one (with wraparound/modulo) **every time the spot completes a cycle, unconditionally** — including when a disruption flips the outcome. Disruption never resets or skips the position pointer; it only changes what gets output for that one occurrence. This makes disruptions self-correcting rather than compounding.
- **Delay mechanic**: `delay_chance` is **rerolled every day** a spot is in PROCESSING (not once at spot time). Delays can in theory stack arbitrarily (e.g. 3+ extra days) — this is intentional and considered realistic ("workforce on strike," "machine broke down"), not something to cap.
- **Cooldown mechanic**: `cooldown_days` is a **fixed** value (no delay/variance layer, unlike processing time). It models industries with genuinely slow turnover (e.g. weekly deliveries) as distinct from industries that want same-day resupply (`cooldown_days = 0`).
- **Shortage/contention rule**: If there aren't enough cars of the right type to service every spot that needs one, spots are serviced **oldest-waiting-first** (a spot carried over from a previous session due to shortage has priority over one that just became empty this session). Ties (spots waiting an equal amount of time) are broken **randomly**. A spot that can't be serviced simply stays in `EMPTY_AWAITING_CAR` and rolls forward to the next session — no special shortage/backlog flag needed; the state model handles it inherently.
- **Same-day pickup + resupply**: A single visit to an industry (the "local job") both pulls any `READY_FOR_PICKUP` spots and immediately attempts to resupply any `EMPTY_AWAITING_CAR` spots at the same industry (subject to availability/priority), in the same job. This falls directly out of the state machine — no special-casing needed — **provided** train classification into Local happens before the local job runs each day (per the daily sequence in Section 3), so that morning arrivals are available for same-day resupply.
- **Job granularity (partial decision)**: one job per industry per day, bundling all needed pulls/spots for that industry into a single job entry — not one job per spot. (Note: physical button/press granularity — whether this maps to one button per industry — is explicitly deferred; see Section 8.)
- **Transfer facility (special industry)**: modeled with `requirement_mode: "random"` and a **weighted** `possible_requirements` list. Each time the spot goes empty, a new requirement is drawn (weighted random) from the list, and the spot then behaves exactly like a normal fixed spot of that type for the full cycle (processing, pattern/disruption if outgoing, etc.). No special code path is needed beyond the weighted draw at "empty" time.
  - **Open implementation detail (unresolved):** if a `possible_requirement` entry itself has an outgoing `pattern`, does that pattern need its own persisted `position` per requirement-type (since the spot may interleave between different requirement types over time), or does `position` reset/behave differently in this case? This was not explicitly resolved and should be revisited when implementing the transfer facility.

## 6. Technology Direction (proposed, not yet confirmed/final)

Discussed earlier in the conversation, before the group pivoted to focus purely on the operations model first:

- Central "brain": small always-on machine (Raspberry Pi or PC) running the job generator, using a lightweight database (SQLite likely sufficient given the small scale of data).
- Hardware nodes: ESP32-based (preferred over classic Arduino for built-in WiFi) at each industry, with a push button and optionally a small I2C character LCD.
- Communication: MQTT (broker like Mosquitto on the central machine) for pub/sub between nodes and the brain — avoids wiring complexity of running serial/USB to every industry.
- "Next day" button: another MQTT node, or wired directly to the central machine if physically close.
- Possible companion web dashboard for full job list / more detail than an LCD can show.

**This is explicitly not finalized** — it was proposed as a direction, and the user has since chosen to finish the software/data model design before returning to hardware/physical UI decisions.

## 7. Ruled-out approaches (and why)

- **JMRI Operations**: rejected because its core model tracks specific individual rolling stock (road name + number), which conflicts with the desired generic car-type-pool model. Also not designed to integrate with custom physical button/display hardware in the way envisioned here.
- **Spreadsheet-based demand generation**: a lighter-weight pattern used by some real operators (random min/max/frequency formulas per industry per car type) was discussed as a known alternative approach in the hobby, but the user explicitly does not want a spreadsheet-based solution.

## 8. Explicitly Deferred Topics

- All physical button/LCD/hardware design decisions (including job granularity at the button level — one button per industry vs. per spot vs. start/complete pairs) — **deferred until the software model is fully specified.**

## 9. Plan Going Forward (agreed order)

1. **Yard-side logic** (unified topic, includes inbound train handling):
   - Inbound train arrival → classification into Local vs. through (East/West)
   - Demand-aware car selection (keeping the right car types flowing into Local based on industry needs)
   - Outbound car sorting (industry pickups → sorting track → East/West outbound groups)
   - Outbound train departure
   - **Open question posed, not yet answered:** when a train "arrives from the east," is that generated from scratch each session (software decides car count/types/local-split), or does a physical staging track already hold real (generic/unidentified) cars, with the software only deciding the split of what's physically there?
2. **Engine assignment logic** (how the system recommends which engine(s) to use per job — simple free-pool assignment vs. tracking engine location/home turf over time)
3. **Job sequencing/dependencies** (whether jobs need to respect ordering — e.g., classification before the local job can run — or whether this is left to operator judgment)
4. (Physical button/display design — deferred, see Section 8)

## 10. Industry/Spot Config Examples Discussed So Far

**Simple fixed outgoing spot, always East:**
```json
{"spot_id": "brewery_out_1", "car_type": "boxcar", "direction": "outgoing", "pattern": ["E"], "position": 0, "disruption_chance": 0.0}
```

**Fixed outgoing spot, every third car West:**
```json
{"spot_id": "brewery_out_2", "car_type": "boxcar", "direction": "outgoing", "pattern": ["E", "E", "W"], "position": 0, "disruption_chance": 0.0}
```

**Weighted random (transfer facility) spot:**
```json
{
  "spot_id": "transfer_1",
  "requirement_mode": "random",
  "possible_requirements": [
    {"car_type": "hopper",  "direction": "incoming", "source": "E", "weight": 5},
    {"car_type": "boxcar",  "direction": "outgoing", "pattern": ["E", "W"], "weight": 3},
    {"car_type": "flatcar", "direction": "outgoing", "pattern": ["W"], "weight": 2}
  ]
}
```

**Slow-turnover spot with cooldown (weekly hopper example):**
```json
{"spot_id": "brewery_hopper_1", "car_type": "hopper", "direction": "incoming", "source": "E", "base_processing_days": 2, "delay_chance": 0.0, "cooldown_days": 3}
```
