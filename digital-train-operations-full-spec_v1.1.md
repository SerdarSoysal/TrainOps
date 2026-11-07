# Digital Train Operations — Full Design Specification

**Version 1.1 — 2026-11-07**

This document is the complete design for the Digital Train Operations project as of this version. It replaces both earlier working files (`digital-train-operations-checkpoint_7-13-26.md` and `digital-train-operations-delta_11-06-26.md`). Those files are kept only for history. Where they disagree with this document, this document wins.

The main body is written to be read by a person. **Appendix A** is a compact, machine-readable version of the same design for use by an AI assistant when resuming work.

---

## 1. Purpose and Philosophy

The project digitizes **operations** on an N scale model railroad. It does not automate train movement: there is no DCC or dispatcher automation. The software replaces car cards and waybills by generating each session's work automatically, driven by the needs of the industries.

- **Every car is tracked individually.** There is a roster of specific numbered cars and engines, and the software always knows where each one is. (This reverses an earlier decision to track only car types. The physical layout requires it: what returns from a hidden loop is exactly what went in.)
- **The software is a custom build.** JMRI Operations was considered and rejected. Even with individual car tracking, JMRI lacks demand-driven planning, the spot mechanics described here (processing delays, disruptions, patterns, cooldowns, oldest-first priority), jobs organized by industry, and an easy fit with the planned physical confirmation buttons. A spreadsheet-based approach was also rejected.
- **The software keeps only the current state.** There is no history or audit trail. The only goal is to say what to do next.

## 2. What the Layout Represents

The layout models a **crew change point with a small yard on a single-track secondary mainline**, set in the modern era, with a local based in town.

- One **manifest** runs in each direction per day. A manifest is a mixed freight train carrying carload traffic to many destinations.
- At this town a manifest only **sets out** a block of cars for local industries and **picks up** a block of cars bound in its direction. It is not broken down or reclassified. Manifests arrive pre-sorted with the set-out block on the rear, as real manifests are sorted at the division yards.
- A dedicated **yard switcher** does all the set-out and pick-up work. Road crews do not switch.
- A **local** serves the industries.
- Modern six-axle power (ES44, AC4400, Dash 9, SD70 and similar) is realistic on all of these, including the local and the yard. Modern Class I railroads routinely move former mainline units into local and yard service.
- There are **no separate through trains.** Traffic that only passes through (for example steel coil cars with no matching industry) rides inside the manifests as continuing cars.

## 3. Physical Layout

West is to the left of the schematic and East to the right.

| Element | Status | Details |
|---|---|---|
| Mainline | Built (East), planned (West extension) | Single track, with passing sidings (left off the schematic) |
| Industry #1, Industry #2 | Built | Share a lead; spurs branch toward the West |
| Industry #3 (transfer facility) | Built | Own spur, branching toward the West |
| Auxiliary yard near Industries #1–2 | Built | Provides runarounds for the local |
| Industry #4 | Uncertain | May be built, or replaced with scenery |
| Yard | Built | 3 stub tracks: **Eastbound**, **Westbound**, **Locals**. Ladder at the West end. About 30–35 cars per track |
| Engine storage | Built | 3 tracks |
| **East world**: hidden return loop | Built | Holds **one** train (about 30 cars + 3 engines). A train can sit there overnight |
| **West world**: stub staging | Planned | 3 tracks, open and fully reachable. One track is a dedicated **engine escape** with a transfer table at the stub end. The other 2 hold about 30–35 cars each |

- **Maximum train length:** 20 cars + 3 engines.
- **Yard switching happens on the main.** That is acceptable because no more than 2 operators will run the layout and the schedule is fully sequential.

## 4. Rolling Stock and Roster

### Cars
Each car record holds:
- Reporting mark and number, and car type.
- **Location:** a world (East loop or West staging), a yard track, a spot at an industry, or in a train.
- **Load status:** `loaded`, `empty`, or `n/a`. It is `n/a` for continuing cars and for any car in a world; there, load status is irrelevant.
- **Last industry that loaded it.** Used by the return-to-shipper rule (Section 7).
- **The world it arrived from** (East or West). Set when it is set out from a manifest, and used to send unwanted empties back (Section 8).

**Any car type can serve an industry.** A car's role comes entirely from the industry configuration. Types that no spot uses (for example steel coil cars) automatically act as through traffic only. The old rule that only flatcars, boxcars and hoppers could serve industries is dropped.

### Engines
Engines belong to one of three groups:

| Group | Use | Size |
|---|---|---|
| Local pool | The local always runs with **2** engines, chosen at random from this pool | Several engines |
| Yard switcher | One **dedicated** engine | 1 |
| Manifest pool | Manifests run with 2–3 engines (Section 9) | About 14 engines |

There are more than enough engines for this model, so engine shortages are not planned for.

## 5. Industries and Spots

An **industry** is a name plus a list of **spots**. All behavior lives in the spots, so there are no special industry types. The transfer facility is just an industry with some fixed spots and one random spot.

### Spot schema

```json
{
  "spot_id": "...",
  "requirement_mode": "fixed | random",

  // --- FIXED MODE ---
  "car_type": "...",
  "direction": "incoming | outgoing",
  "source": "E | W",                 // incoming only: which direction the loaded car comes from
  "pattern": ["E", "E", "W"],        // outgoing only: ordered, repeating destination list
  "position": 0,                     // RUNTIME STATE: pointer into pattern
  "disruption_chance": 0.0,          // chance per completion to flip the pattern's destination
  "base_processing_days": 2,
  "delay_chance": 0.0,               // rolled every day while processing
  "cooldown_days": 0,                // fixed, no variance

  // --- RANDOM MODE ---
  "possible_requirements": [
    {
      "car_type": "...",
      "direction": "incoming | outgoing",
      "source_weights": {"E": 0.5, "W": 0.5},       // incoming: rolled fresh on every draw
      "destination_weights": {"E": 0.5, "W": 0.5},  // outgoing: rolled fresh on every draw
      "weight": 3,                                   // chance of this requirement being drawn
      "base_processing_days": 2,                     // in random mode these three fields live here
      "delay_chance": 0.1,
      "cooldown_days": 0
    }
  ]
}
```

Configuration (`pattern`, `possible_requirements` and so on) is static. Runtime state (`position`, spot state, day counters) persists and is never reset by reloading the configuration.

### Spot cycle

```
EMPTY_AWAITING_CAR → PROCESSING (counts down; delay rolled daily)
                   → READY_FOR_PICKUP
                   → [pulled by the local]
                   → COOLDOWN (fixed days; skipped if 0)
                   → EMPTY_AWAITING_CAR  (random spots draw a new requirement here)
```

- **Incoming spot:** needs a **loaded** car of the right type from the right direction. When pulled, the car is empty.
- **Outgoing spot:** needs an **empty** car of the right type. When pulled, the car is loaded and goes East or West according to `pattern` and `position` (fixed spots) or `destination_weights` (random spots).

### Spot rules
- **Pattern position** (fixed spots only) advances by one on **every** completion, with wraparound, even when a disruption flips that one result. Disruptions correct themselves; they don't build up.
- **Delays** are rolled every processing day and can stack without limit. This is intentional.
- **Cooldown** is a fixed number of days. It models industries with slow turnover.
- **Random spots** have no pattern memory. Each draw rolls its direction fresh.
- **Rolled a day early:** delay rolls and random-requirement draws (including a random spot's source or destination) are made **one day ahead**. This makes the forecast exact (Section 10). At the layout it looks no different.
- **Shortage priority:** when cars are short, the spot that has waited **longest** is served first, with random tie-breaks. A spot that can't be served stays empty and rolls forward.
- **One visit per industry per day:** the local pulls ready cars and spots new cars at an industry in the same visit.

## 6. The Two Worlds (Rest of the Railroad)

East and West are **real physical places**, each standing in for the rest of the railroad in that direction. Both keep their state between sessions, and both are **rebuilt before every session** as a chore (Section 11).

| | East world: return loop | West world: stub staging |
|---|---|---|
| Capacity | One train | 2 car tracks × about 30–35 cars, plus an engine escape track |
| Contents | **Closed set:** exactly the cars that went East on the previous eastbound manifest | **Pool:** every car that has gone West and not yet come back |
| Rebuild | The train is re-sorted using the yard tracks. Its cars must never mix with real yard cars. Nothing is added or removed; every car rides out | The eastbound manifest is built from any cars in staging. The rest stay as spares |
| Planning consequence | Tomorrow's East-sourced demand can only use cars sent East **today** | The software can choose freely from the whole pool |

- Inside a world, loads are `n/a`. A car's load is **assigned when it is chosen for a Local block** (Section 7).
- A world stands in for many places, so variety comes from re-sorting, reassigning loads, and swapping engines.

## 7. Loads

- **Only cars going to or coming from the local have a load status.** Continuing cars and cars in a world are `n/a`.
- **When a car is chosen for a Local block, the target spot sets its load:** loaded for an incoming spot, empty for an outgoing spot.
- **Return-to-shipper rule:** if a car's next assignment is the **same industry that last loaded it**, it must arrive **empty**, so it can only go to an outgoing spot there. For any other industry it can arrive loaded or empty as needed.
- **Cars pulled from industries keep their real load** while they sit on the Eastbound or Westbound yard tracks. Once they enter a world, the load becomes `n/a`.
- **Unwanted empties never pile up.** Empties go into a world and come back as whatever is needed later.

## 8. Routing Cars Pulled From Industries

- **Loaded cars from outgoing spots** go to the **Eastbound** or **Westbound** yard track, according to pattern, position and disruption (fixed spots) or the rolled destination (random spots).
- **Empty cars from incoming spots:**
  1. If **any outgoing spot on the layout can use that car type** (a fixed outgoing spot of that type, or a random spot with an outgoing requirement for it), the empty waits on the **Locals** track for reuse. It waits **up to N days** (default **2**, configurable).
  2. If no spot could use it (for example empty propane tankers with no propane loader), it goes straight to the yard track for the **world it came from**.
  3. If it is still unused after N days, it goes back to the world it came from.

## 9. Building Trains

### Car selection and order
- **The Local block always goes at the rear.** It is the block the switcher cuts off at this town.
- **The Local block is filled from any car of a matching type that is available in that world.** A car that was a continuing car yesterday can be today's Local car. Loads are assigned as in Section 7.
- **The rest of the train (continuing cars) is in random order.**
- **Length rule:** `arriving cars − Local set-out + pick-up block ≤ 20`. Every pick-up block is known before the session starts, so the builder leaves room for it. If a pick-up track holds more cars than fit, the **oldest go first** and the rest wait a day.
- **West staging balance:** the eastbound manifest is built to about the **same length as the westbound manifest that arrived** in staging, with a hard check against staging capacity, so West staging neither fills up nor empties out.
- **East-side supply:** the eastbound manifest (including the pick-up block it adds at the yard) must carry suitable cars for **tomorrow's** East-sourced demand, because the East is a closed set.

### Power
- **The local:** always 2 engines, chosen at random from the local pool.
- **A manifest:** **2 engines at 15 cars or fewer, 3 engines at 16 or more.** The length that counts is the **longer** of the train's arriving and departing lengths.
- **Eligible engines for a manifest:** the engines currently at that train's world (those that arrived there yesterday) plus engines in storage. They are chosen at random.
- **Leftover engines** at either world go **back to storage** during the pre-session chore.

## 10. Demand Forecast

Cars for the local are decided a day before they are used:

- **From the East:** tomorrow's westbound arrival can only contain cars that ride East on **today's** eastbound manifest. Those cars are set out before tomorrow's local runs, so they serve tomorrow's demand.
- **From the West:** today's eastbound manifest sets out its Local block **after** today's local has run, so those cars are spotted **tomorrow**.

So each morning the software needs to know which spots will need cars **tomorrow**, of what type and from which direction. All of this comes from the industry configuration and the current spot states: spots already waiting, cooldowns ending, ready cars that today's local will pull, and the day-early rolls. **No forecast-specific configuration is needed.**

**Shortages are accepted.** If no suitable car is available, the spot waits and rolls forward. Since this is a closed system and the forecast keeps counting waiting spots, shortages correct themselves quickly, usually by the next day.

## 11. Daily Sequence

Strictly sequential: each step finishes before the next starts. The main is needed for yard work, and there aren't enough arrival and departure tracks to overlap steps.

| Step | Event | Who |
|---|---|---|
| 0 | **Pre-session chores:** rebuild the westbound manifest in the East loop (re-sorted using the yard tracks) and the eastbound manifest in West staging, and make the engine moves | Operator, from the chore sheets |
| 1 | Westbound manifest leaves the East loop and arrives at the yard, holding on the main | Road crew |
| 2 | **Switcher job A:** cut the rear Local block and shove it into the Locals track; pick up the Westbound track and add it to the rear | Yard switcher |
| 3 | Westbound manifest runs to West staging | Road crew |
| 4 | **Local job:** spot and pull at each industry; on return, leave the returned cars on the main | Local crew |
| 5 | **Switcher job B:** sort the local's returned cars onto Eastbound, Westbound or Locals | Yard switcher |
| 6 | Eastbound manifest leaves West staging and arrives at the yard (only after job B is finished) | Road crew |
| 7 | **Switcher job C:** cut the rear Local block into the Locals track; pick up the Eastbound track and add it to the rear | Yard switcher |
| 8 | Eastbound manifest runs into the East loop and sits there overnight | Road crew |
| — | **Day advance** (after any corrections, Section 13) | Operator |

Results of this order:
- Cars set out from the westbound manifest can be spotted **the same day**. That includes refilling spots the local empties today, because those spots are known in advance.
- Cars set out from the eastbound manifest are spotted **the next day**.
- The westbound pick-up block holds **yesterday's** local pulls. The eastbound pick-up block holds **today's**.
- The East loop empties at step 1 and fills at step 8, so it never needs room for two trains.

## 12. Session Work Lists

The software produces five kinds of list each session.

### 12.1 Pre-session chore sheet (one per world)
Three sections, always in this order. A section with nothing to do says **"none"**.

```
WEST STAGING — Eastbound manifest
1. Engines from storage → staging:  BNSF 7710
2. Engines from staging → storage:  BNSF 6012, UP 5509
3. Train list
   Engines (lead first):  BNSF 4521, BNSF 7710
   Cars (head → rear):
     1  TTX 81234    flatcar
     2  ATSF 5521    boxcar
     ...
    15  UP 330112    coil car
    16  GATX 7721    tanker   LOADED → Transfer facility   (Local block)
    17  CSXT 14420   boxcar   EMPTY  → Industry #1         (Local block)

EAST LOOP — Westbound manifest
1. Engines from storage → staging:  none
2. Engines from staging → storage:  CSX 3150
3. Train list
   ...
```

Load and destination appear only on Local-block cars.

### 12.2 Switcher jobs A and C (one per manifest)
```
WESTBOUND MANIFEST — switcher
1. Cut the rear 3 cars → shove into Locals track:
     GATX 7721 tanker, CSXT 14420 boxcar, ATSF 5521 boxcar
2. Pick up from Westbound track → add to rear:
     UP 41230 hopper, BNSF 72281 boxcar
(3. Left on Westbound track for tomorrow: ...   — only if the length limit is hit)
```

### 12.3 Local job (by industry)
The local takes **specific** cars from the Locals track. The order of cars in the local train doesn't matter.
```
INDUSTRY #1
  Spot  CSXT 14420 (boxcar, empty)   → spot brewery_out_1
  Pull  BNSF 72281 (boxcar, loaded)  ← spot brewery_out_2
TRANSFER FACILITY
  Spot  GATX 7721 (tanker, loaded)   → spot transfer_tanker
  Pull  TILX 30018 (tanker, empty)   ← spot transfer_tanker
```

### 12.4 Switcher job B (sorting the local's returned cars)
```
YARD JOB — sort local's returned cars (on the main)
  → Eastbound track:  BNSF 72281 boxcar (loaded)
  → Westbound track:  UP 41230 hopper (loaded)
  → Westbound track:  TILX 30018 tanker (empty, returning to origin W)
  → Locals track:     ATSF 5521 boxcar (empty, held for reuse)
```

## 13. Corrections, Day Advance and Persistence

- **The default is that every job was done as listed.** Advancing the day applies all listed moves to the car records.
- **Before advancing, two correction tools are available:**
  - **Skip a job** or part of one. Those moves don't happen and the cars stay where they were. Spots that weren't served keep waiting, which the spot cycle already handles. Ending a session early means skipping the rest of the jobs.
  - **Edit a car:** set its actual location (track, spot or world), for example to fix a wrong car spotted, or a record found to be out of step with the layout.
- **Persistence:** the full state (every car, engine and spot, and all counters) is saved at every day advance. Turning the system off loses nothing.
- **Cold start**, done once or after a deliberate reset: enter the roster (cars by mark, number and type; engines by mark, number and group). Then say which cars are physically in the East loop and which are in West staging. Every spot and yard track starts empty, and the industries fill up over the first few sessions.
- **Roster changes:** a new car is added into a world. A retired car is removed wherever it is. No reset is needed.
- **No backups and no history.** If the state is lost, do a cold start.

## 14. Technology Direction (proposed, not final)

- The central program would be Python on a PC or Raspberry Pi, with SQLite for the saved state.
- Work lists would be printed and/or shown on a simple web page. To be decided when building starts.
- **Hardware stays deferred.** The earlier ideas were ESP32 nodes at each industry with push buttons and small LCDs, MQTT messaging, and a "next day" button. Nothing is decided, including how buttons map to jobs.

## 15. Still Open

- **Industry configuration:** spot counts and settings for Industries #1–3, and whether Industry #4 is built. To be done later.
- **Where empties for outgoing spots come from when no held empty is on Locals:** which world supplies them, East, West or either. Small; decide during implementation.
- **Software platform and output format** (Section 14).
- **Hardware and physical confirmation design** (deferred).
- **Ideas for later versions:** varying the daily schedule (more or fewer trains, weekday and weekend patterns).

## 16. Decision History (superseded ideas, for reference)

| Earlier idea | Replaced by | Why |
|---|---|---|
| Track car types only, no roster | Individual car tracking | Hands-off physical worlds return exactly what went in |
| One stub staging for both directions; E/W only labels | A physical East loop and West stub staging | The layout provides both |
| Staging holds no state; arrivals simply declared | Stateful worlds rebuilt every session | Arrivals must be real cars |
| Single-track West loop (Option B) | 3-track stub staging | User changed their mind; more realistic, and the West becomes a pool of cars |
| Trains broken down in the yard; through trains with engine swaps | Manifests set out and pick up blocks; no through trains | Modern practice; fits the track capacity |
| Westbound manifest works the yard itself | The switcher works both manifests | Consistency |
| Arrivals sized by that moment's demand | Day-ahead forecast with day-early rolls | Cars are decided a day before use |
| Only flatcars, boxcars and hoppers serve industries | Any car type can serve an industry | The transfer facility and propane examples |
| Outgoing demand never feeds arrivals | Worlds supply empties for outgoing spots | Loads are assigned when a train is built |

---

## Appendix A — Machine-Readable Spec (AI-facing)

```yaml
spec: digital-train-operations
version: "1.1"
date: 2026-11-07
supersedes: [checkpoint_7-13-26.md, delta_11-06-26.md]
resume_instruction: "Read this appendix only; main body = human prose of same content."
next_version: "1.2 (new file digital-train-operations-full-spec_v1.2.md)"
user_style: "Dictates via speech-to-text; literal 'Period.'/'comma'/'colon' words are punctuation artifacts."

philosophy:
  scope: digitize ops paperwork; no train-movement automation
  car_tracking: individual (roster)
  build: custom (JMRI rejected: no demand planning, spot mechanics, industry jobs, button fit; spreadsheet rejected)
  history: none; state = current only

prototype:
  framing: modern-era crew-change point + small yard, single-track secondary main, based local
  trains_per_day: {manifest_EB: 1, manifest_WB: 1, local: 1}
  through_trains: none  # through-only car types ride as continuing cars in manifests
  manifests: arrive presorted; Local block at REAR; switcher does all set-out/pick-up; road crews never switch
  power_realism: modern 6-axle OK on local/yard

layout:
  orientation: {W: left, E: right}
  main: single track; passing sidings exist; yard switching on main OK (<=2 operators)
  industries: {ind1: built, ind2: built, ind3_transfer: built, ind4: uncertain}
  spurs: ind1/ind2 shared lead and ind3, all diverge toward W; aux yard near ind1/2 gives runarounds
  yard: {tracks: [Eastbound, Westbound, Locals], type: stub, ladder: W end, cap_each: 30-35}
  engine_storage: 3 tracks
  world_E: {type: hidden_return_loop, built: true, capacity_trains: 1, cap: "~30 cars+3 eng", overnight: true}
  world_W: {type: stub_staging, built: false, tracks: 3, car_tracks: 2, cap_each: 30-35, engine_escape: "1 track + transfer table at stub end", visible_reachable: true}
  max_train: {cars: 20, engines: 3}

roster:
  car_fields: [mark, number, type, location, load(loaded|empty|n/a), last_loaded_at_industry, origin_world(E|W)]
  location_values: [world_E, world_W, yard:<track>, spot:<id>, in_train]
  any_car_type_can_serve_industry: true  # role from config; unused types = through-only
  engine_groups:
    local_pool: {per_train: 2, pick: random}
    switcher: {count: 1, dedicated: true}
    manifest_pool: {size: ~14, per_train: "2 if len<=15 else 3", len_basis: "max(arriving, departing)", eligible: "engines at that world + storage", pick: random}
  engine_shortage: not modeled (ample)

spots:
  schema: per checkpoint_7-13 (fixed: car_type,direction,source|pattern,position,disruption_chance,base_processing_days,delay_chance,cooldown_days; random: possible_requirements[car_type,direction,source_weights|destination_weights,weight,base_processing_days,delay_chance,cooldown_days])
  states: [EMPTY_AWAITING_CAR, PROCESSING, READY_FOR_PICKUP, pulled, COOLDOWN]
  incoming: needs loaded car of type from source dir; pulled -> empty
  outgoing: needs empty; pulled -> loaded, dest by pattern/position(+disruption flip) or destination_weights
  position: advances every completion unconditionally (incl disruption)
  delay: rolled daily, uncapped stacking
  cooldown: fixed days
  random_mode: no position; fresh E/W roll per draw; draw at EMPTY
  preroll: delay rolls + random draws (incl source/dest) done ONE DAY AHEAD -> exact forecast
  shortage: oldest-waiting first, random tiebreak; unserved stays EMPTY, rolls forward
  local_visit: one per industry per day, pull+spot combined
  config_vs_state: config static; runtime state persists, never reset on reload

worlds:
  rebuilt: before every session (chore)
  loads_inside: n/a
  E: closed set = exactly cars of prior EB manifest; re-sorted via yard tracks, never mixed with yard cars; nothing added/removed; all ride out
  W: pool; EB built from any staging cars; rest stay as spares; WB arrival couples onto spares OK

loads:
  tracked_only_for: local-bound/local-originated cars; continuing + world cars = n/a
  assign_at: Local-block selection; incoming spot -> loaded; outgoing spot -> empty
  return_to_shipper: if target industry == last_loaded_at -> must be empty (outgoing spot only)
  pulled_cars: keep real load on Eastbound/Westbound tracks; -> n/a on entering world

routing_pulled_cars:
  loaded_from_outgoing: Eastbound|Westbound track per pattern/dest
  empty_from_incoming:
    if_type_used_by_any_outgoing_spot: hold on Locals up to N days (default 2, configurable), then -> track toward origin_world
    else: immediately -> track toward origin_world

train_building:
  local_block: rear; filled from ANY matching-type car available in that world (prior role irrelevant)
  continuing: random order ahead of local block
  length_rule: "arriving - setout + pickup <= 20"; pickups known pre-session; overflow -> oldest first, rest wait
  W_balance: EB length ~= WB length that arrived in W; hard check vs W capacity
  E_supply: EB (+ its Eastbound pickup) must carry cars for TOMORROW's E-sourced demand
  leftover_engines: both worlds -> storage at chore

forecast:
  E_sourced_for_day_D: chosen from cars sent E on day D-1 EB; set out D step2 before local -> same-day spot
  W_sourced: EB set out at step7 after local -> spotted next day
  inputs: industry config + spot state + prerolls; no extra config
  shortages: accepted; self-correct ~next day

daily_sequence:  # strictly sequential, no overlap
  0: pre-session chores (rebuild WB in E loop via yard tracks; rebuild EB in W staging; engine moves)
  1: WB leaves E loop -> yard (holds on main)
  2: switcher job A: cut rear Local block -> Locals; pick up Westbound track -> rear
  3: WB -> W staging
  4: local job; leaves returned cars on main
  5: switcher job B: sort returned cars -> Eastbound|Westbound|Locals
  6: EB leaves W staging -> yard (only after 5 done; track-capacity constraint)
  7: switcher job C: cut rear Local block -> Locals; pick up Eastbound track -> rear
  8: EB -> E loop, overnight
  advance: after corrections
  facts: WB pickup = yesterday's pulls; EB pickup = today's pulls; E loop empty at 1, filled at 8

outputs:
  chore_sheet_per_world: ["1 engines storage->staging", "2 engines staging->storage", "3 train list: engines lead-first; cars head->rear; local-block cars show load+dest"]; empty section prints "none"
  switcher_A_C: ["cut rear N cars (listed) -> Locals", "pick up <dir> track (listed) -> rear", "optional: left behind (length limit)"]
  local: per industry: "Spot <car> -> <spot>" / "Pull <car> <- <spot>"; specific cars; train order irrelevant
  switcher_B: per car -> Eastbound|Westbound|Locals (with reason: loaded dest / empty to origin / held)

corrections_persistence:
  default: all jobs done as listed; day advance commits
  tools: [skip job or part (cars stay; spots keep waiting), edit car location]
  early_end: skip remaining jobs
  persist: full state saved each day advance (SQLite assumed)
  cold_start: once or on reset; enter roster; declare cars in E loop vs W staging; spots+yard empty
  roster_changes: add new car into a world; remove retired car anywhere
  backups: none (loss -> cold start)

tech_proposed: {brain: "Python on PC/RPi", db: SQLite, output: "print and/or web page TBD", hardware: deferred (ESP32+button+LCD, MQTT, next-day button)}

open:
  - industry configs (spot counts ind1-3; ind4 existence) — later
  - source world for empties for outgoing spots when no held empty on Locals (E, W, either) — decide at implementation
  - platform/output format
  - hardware (deferred)
  - v2: vary daily schedule (train count, weekday/weekend)

derived_not_explicitly_confirmed:
  - outgoing-spot empties: held Locals empties used before world-supplied empties
  - E loop rebuild ends with train back in loop ready for step 1 (operator's method)
```
