# Digital Train Operations — Full Design Specification

**Version 1.4 — 2026-11-09**

This document is the complete design for the Digital Train Operations project as of this version. It replaces version 1.3 (`digital-train-operations-full-spec_v1.3.md`) and all earlier working files, which are kept only for history. Where they disagree with this document, this document wins.

The main body is written to be read by a person. **Appendix A** is a compact, machine-readable version of the same design for use by an AI assistant when resuming work.

**What changed since 1.3:** this version adds the **data model** (Section 16).
- **Configuration file:** the industry configuration and the settings live in a YAML file.
- **Database:** the current state lives in five SQLite tables.
- **Everything else is worked out when needed.** That covers the job lists, the forecast and the spot display text.
- **Roster entry:** the cold-start roster is imported from CSV files. Single cars are added or retired on the web page.
- **Spot editing:** the edit tool can now also set a spot's state (Section 14).
- **West staging stays a pool:** the software does not track which staging track a car is on.
- **Plain language everywhere:** every value a person reads or types uses plain words, never single letters or codes (Section 16).

Version 1.3 had settled how the manifests are made up: a random Eastbound length of 12–20 cars and exception overload trains. See Section 19 for the full history.

---

## 1. Purpose and Philosophy

The project digitizes **operations** on an N scale model railroad. It does not automate train movement: there is no DCC or dispatcher automation. The software replaces car cards and waybills by generating each session's work automatically, driven by the needs of the industries.

- **Every car is tracked individually.** There is a roster of specific numbered cars and engines, and the software always knows where each one is. (This reverses an earlier decision to track only car types. The physical layout requires it: what returns from a hidden loop is exactly what went in.)
- **The operator confirms work as it happens.** The software's records follow the layout through signals (Section 13), not through one bulk update at the end of the session.
- **The software is a custom build.** JMRI Operations was considered and rejected. Even with individual car tracking, JMRI lacks demand-driven planning, the spot mechanics described here (processing delays, disruptions, patterns, cooldowns, oldest-first priority), jobs organized by industry, and an easy fit with physical confirmation buttons. A spreadsheet-based approach was also rejected.
- **The software keeps only the current state.** There is no history or audit trail. The only goal is to say what to do next.

## 2. What the Layout Represents

The layout models a **crew change point with a small yard on a single-track secondary mainline**, set in the modern era, with a local based in town.

- One **manifest** runs in each direction per day. A manifest is a mixed freight train carrying carload traffic to many destinations.
- At this town a manifest only **sets out** a block of cars for local industries and **picks up** a block of cars bound in its direction. It is not broken down or reclassified. Manifests arrive pre-sorted with the set-out block on the rear, as real manifests are sorted at the division yards.
- A dedicated **yard switcher** does all the set-out and pick-up work. Road crews do not switch.
- A **local** serves the industries.
- Modern six-axle power (ES44, AC4400, Dash 9, SD70 and similar) is realistic on all of these, including the local and the yard. Modern Class I railroads routinely move former mainline units into local and yard service.
- There are **no separate through trains.** Traffic that only passes through (for example steel coil cars with no matching industry) rides inside the manifests as continuing cars.
- **The two worlds stand for distant places.** For example, if the yard were in Chicago, West staging would stand for Seattle and everything else westbound. A car loaded here for the West goes to some industry out West, gets unloaded there and comes back empty from the West.

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

- **Train length:** normally up to 20 cars + 3 engines. An occasional **exception overload train** of about 21–22 cars is allowed (Section 9). The hard limits are the East loop (about 30 cars) and the West staging tracks (about 30–35 cars each).
- **Yard switching happens on the main.** That is acceptable because no more than 2 operators will run the layout and the schedule is fully sequential.
- **The Locals track is not capacity-checked.** It holds over 30 cars, and the local is expected to run with only 7–10 cars.

## 4. Rolling Stock and Roster

### Cars
Each car record holds:
- Reporting mark and number, and car type.
- **Location:** a world (East loop or West staging), a yard track, a spot at an industry, or in a train (westbound manifest, eastbound manifest, or the local).
- **Load status:** `loaded`, `empty`, or `not tracked`. It is `not tracked` for continuing cars and for any car in a world; there, load status is irrelevant.
- **Last industry that loaded it.** Used by the return-to-shipper rule (Section 7).
- **The world it arrived from** (East or West). Set when it is set out from a manifest, and used to send unwanted empties back (Section 8).
- **Assigned spot**, if any. Set when the car is chosen for a Local block; cleared when its set-out is signalled done. A car that wasn't delivered keeps its assigned spot (Section 8).
- **Days held on Locals**, for empties waiting there for reuse (Section 8).
- **Destination world**, for a loaded car pulled from an outgoing spot. It carries the destination fixed at READY_FOR_PICKUP (Section 5) so job B can route the car.

**Any car type can serve an industry.** A car's role comes entirely from the industry configuration. Types that no spot uses (for example steel coil cars) automatically act as through traffic only.

### Engines
Engines belong to one of three groups:

| Group | Use | Size |
|---|---|---|
| Local pool | The local always runs with **2** engines, chosen at random from this pool | Several engines |
| Yard switcher | One **dedicated** engine | 1 |
| Manifest pool | Manifests run with 2–3 engines (Section 9) | About 14 engines |

There are more than enough engines for this model, so engine shortages are not planned for.

## 5. Industries and Spots

An **industry** is a name plus a list of **spots**. All behavior lives in the spots, so there are no special industry types. The transfer facility is just an industry with some fixed spots and one random spot. **A spot holds one car.**

### Spot schema

```json
{
  "spot_id": "...",                  // internal key, never shown to operators
  "name": "Loading door 2",          // what operators see in every list and display
  "requirement_mode": "fixed | random",

  // --- FIXED MODE ---
  "car_type": "...",
  "direction": "incoming | outgoing",
  "source": "East | West",           // incoming only: which direction the loaded car comes from
  "pattern": ["East", "East", "West"], // outgoing only: ordered, repeating destination list
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
      "source_weights": {"East": 0.5, "West": 0.5},       // incoming: rolled fresh on every draw
      "destination_weights": {"East": 0.5, "West": 0.5},  // outgoing: rolled fresh on every draw
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
EMPTY_AWAITING_CAR ──(set-out signalled done)──► PROCESSING (counts down at each day advance; delay rolled daily)
                                                → READY_FOR_PICKUP  (outgoing: destination fixed here)
READY_FOR_PICKUP   ──(pull signalled done)─────► COOLDOWN (fixed days; skipped if 0)
                                                → EMPTY_AWAITING_CAR  (random spots draw a new requirement here)
```

- **Incoming spot:** needs a **loaded** car of the right type from the right direction. When pulled, the car is empty.
- **Outgoing spot:** needs an **empty** car of the right type. When pulled, the car is loaded and goes East or West.
- **The spot state is the visible demand signal.** Each spot shows its state in plain language, on the web page now and on LCDs later. Examples (exact wording set during implementation):
  - "Industry #3, spot 2: needs loaded boxcar from East"
  - "Industry #3, spot 2: needs loaded boxcar from East — CSXT 14420 waiting on Locals track"
  - "Industry #1, spot 1: loading TILX 30018"
  - "Industry #1, spot 1: TILX 30018 ready for pickup"

### Spot rules
- **The outgoing destination is fixed when processing completes** (the spot becomes READY_FOR_PICKUP). For a fixed spot that is `pattern[position]`, with the disruption roll applied then. For a random spot it is the destination rolled at the draw. The car keeps that destination even if its pull is delayed.
- **Pattern position** (fixed spots only) advances by one on **every** completion, with wraparound, even when a disruption flips that one result. Disruptions correct themselves; they don't build up.
- **Delays** are rolled every processing day and can stack without limit. This is intentional.
- **Cooldown** is a fixed number of days. It models industries with slow turnover.
- **Random spots** have no pattern memory. Each draw rolls its direction fresh.
- **Rolled a day early:** delay rolls and random-requirement draws (including a random spot's source or destination) are made **one day ahead**. This makes the forecast exact (Section 10). At the layout it looks no different. They always apply to the spot's **actual** state, so a skipped move simply shifts that spot's timeline by a day.
- **Shortage priority:** when cars are short, the spot that has waited **longest** is served first, with random tie-breaks. A spot that can't be served stays empty and rolls forward.
- **One visit per industry per day:** the local pulls ready cars and spots new cars at an industry in the same visit.
- **Pull before set-out.** If a spot has a car to pull and a car to set out (a swap, typical for a spot with no cooldown), the pull must be signalled done before the set-out can be. If the pull doesn't happen, the set-out can't either. The two remain separate signals, so the local can still do one without the other, for example pull a ready car when no replacement is available.

## 6. The Two Worlds (Rest of the Railroad)

East and West are **real physical places**, each standing in for the rest of the railroad in that direction. Both keep their state between sessions, and both are **rebuilt before every session** as a chore (Section 11).

| | East world: return loop | West world: stub staging |
|---|---|---|
| Capacity | One train | 2 car tracks × about 30–35 cars, plus an engine escape track |
| Contents | **Closed set:** exactly the cars that went East on the previous eastbound manifest | **Pool:** every car that has gone West and not yet come back |
| Rebuild | The train is re-sorted using the yard tracks. Its cars must never mix with real yard cars. Nothing is added or removed; every car rides out. The rebuild ends with the train back in the loop, ready for step 1 | The eastbound manifest is built from any cars in staging. The rest stay as spares |
| Planning consequence | Tomorrow's East-supplied cars can only be cars sent East **today** | The software can choose freely from the whole pool |

- Inside a world, loads are `not tracked`. A car's load is **assigned when it is chosen for a Local block** (Section 7).
- A world stands in for many places, so variety comes from re-sorting, reassigning loads, and swapping engines.

## 7. Loads

- **Only cars going to or coming from the local have a load status.** Continuing cars and cars in a world are `not tracked`.
- **When a car is chosen for a Local block, the target spot sets its load:** loaded for an incoming spot, empty for an outgoing spot.
- **A car that isn't delivered keeps the load it was given.**
- **Return-to-shipper rule:** if a car's next assignment is the **same industry that last loaded it**, it must arrive **empty**, so it can only go to an outgoing spot there. For any other industry it can arrive loaded or empty as needed.
- **Cars pulled from industries keep their real load** while they sit on the Eastbound or Westbound yard tracks. Once they enter a world, the load becomes `not tracked`.
- **Unwanted empties never pile up.** Empties go into a world and come back as whatever is needed later.

## 8. Car Flow To and From the Industries

### Supplying cars to spots
- **Incoming spot:** a loaded car of the right type from the spot's source world (fixed `source`, or the rolled source for a random spot).
- **Outgoing spot (empty needed):**
  1. **A held empty of the right type on the Locals track is used first**, whichever world it came from. It is already in the yard.
  2. Otherwise the empty comes from **the world the loaded car will be shipped to** (the shuttle model). A car to be loaded for the West comes empty from West staging; a car to be loaded for the East comes empty from the East loop. The car is in effect shuttling between an industry on the layout and an unseen industry in that direction.
  - The direction used is the **scheduled** destination: `pattern[position]` for a fixed spot, or the destination rolled at the draw for a random spot. A disruption is rolled only when processing completes, so occasionally a car supplied from one side is shipped to the other. That is accepted.
- **Undelivered cars keep their assignment.** A car the local doesn't deliver goes back to the Locals track (job B), still assigned to its spot, and is first in line on the next run. The forecast treats that spot as covered, so no second car is sent for it.

### Routing cars pulled from industries
- **Loaded cars from outgoing spots** go to the **Eastbound** or **Westbound** yard track, according to the destination fixed when processing completed.
- **Empty cars from incoming spots:**
  1. If **any outgoing spot on the layout can use that car type** (a fixed outgoing spot of that type, or a random spot with an outgoing requirement for it), the empty waits on the **Locals** track for reuse. It waits **up to N days** (default **2**, configurable), counted at each day advance.
  2. If no spot could use it (for example empty propane tankers with no propane loader), it goes straight to the yard track for the **world it came from**.
  3. If it is still unused after N days, it goes back to the world it came from.

## 9. Building Trains

### The Local blocks are driven by demand
Both Local blocks are decided at the day advance from the forecast (Section 10). Each one contains the cars the spots need, minus anything already covered by held empties or undelivered cars on the Locals track. The two blocks serve different days:
- **Westbound Local block** (cut by job A, step 2): serves **today's** East-supplied demand. Those cars are spotted by the same day's local.
- **Eastbound Local block** (cut by job C, step 7): serves **tomorrow's** West-supplied demand. It is set out after today's local has run, so its cars are spotted the next day.

### Car selection and order
- **The Local block always goes at the rear.** It is the block the switcher cuts off at this town.
- **The Local block is filled from any car of a matching type that is available in that world.** A car that was a continuing car yesterday can be today's Local car. Loads are assigned as in Section 7.
- **The rest of the train (continuing cars) is in random order.**
- **Every westbound car that is not in the Local block continues to West staging.** Job A cuts only the Local block. The rest of the train, plus the Westbound pick-up block added at the rear, runs on to the West.

### Westbound manifest (from the East loop)
- **Its cars are fixed:** exactly the cars the previous eastbound manifest took into the East loop, re-sorted so the Local block is at the rear. Its length is therefore whatever yesterday's eastbound train delivered to the East.

### Eastbound manifest (from West staging)
- **Length drawn at random:** each day the eastbound manifest leaves West staging with a random length between **12 and 20 cars**. Both numbers are configuration values with defaults of 12 and 20. The length counts the train as it **leaves West staging**, before any yard work.
- **Raised to the minimum it must carry:** the train is never shorter than its Local block plus the cars needed for **tomorrow's East-supplied demand** that its Eastbound pick-up block won't already cover. If the draw is lower than that, it is raised to the minimum.
- **Lowered to what staging holds:** if West staging has fewer suitable cars than the draw, the train runs shorter. If it can't even meet the demand, the normal shortage rules apply (Section 10).
- **Continuing cars are picked at random** from the West staging pool. The cars not chosen stay behind as spares.
- **East-side supply:** the eastbound manifest, including the pick-up block it adds at the yard, must carry suitable cars for **tomorrow's** East-supplied demand. That means loaded cars for East-sourced incoming spots and empties for outgoing spots scheduled to ship East. The East is a closed set, so those cars must be on this train.
- **West staging capacity** is still checked as a hard limit.

### Length after yard work: the exception overload train
- **Pick-up blocks are never left behind.** Each switcher job adds the **whole** pick-up track to its manifest: the Westbound track in job A, the Eastbound track in job C.
- After yard work, a manifest's length is: arriving cars − Local set-out + pick-up block. **If that comes to more than 20 cars, the train runs as an exception overload train.** This is expected to be rare and only by 1–2 cars.
- **An overload carries into the next day.** The East loop is a closed set whose cars all ride out, so a 22-car eastbound arrival becomes a 22-car westbound manifest the next morning. After job A, that westbound train can be over 20 as well, and the same rule applies.
- **The hard limits are the destinations:** the East loop holds about 30 cars, and West staging must have room. If one of these were ever exceeded, the oldest pick-up cars would go first and the rest would wait a day. That is a safeguard only and isn't expected to happen.

### Power
- **The local:** always 2 engines, chosen at random from the local pool.
- **A manifest:** **2 engines at 15 cars or fewer, 3 engines at 16 or more.** The length that counts is the **longer** of the train's arriving and departing lengths. An overload train always gets 3.
- **Eligible engines for a manifest:** the engines currently at that train's world (those that arrived there yesterday) plus engines in storage. They are chosen at random.
- **Leftover engines** at either world go **back to storage** during the pre-session chore.

## 10. Demand Forecast

Cars for the local are decided a day before they are used:

- **From the East:** tomorrow's westbound arrival can only contain cars that ride East on **today's** eastbound manifest. Those cars are set out before tomorrow's local runs, so they serve tomorrow's demand.
- **From the West:** today's eastbound manifest sets out its Local block **after** today's local has run, so those cars are spotted **tomorrow**.

So each morning the software needs to know which spots will need cars **tomorrow**, of what type and from which direction. All of this comes from the industry configuration and the current spot states: spots already waiting, cooldowns ending, ready cars that today's local will pull, cars already assigned (including undelivered cars waiting on Locals), and the day-early rolls. **No forecast-specific configuration is needed.**

- **"From which direction"** means the source world for incoming spots, and the scheduled destination world for outgoing spots that no held empty will cover (Section 8).
- **The forecast assumes today's local does all its listed work.** When it doesn't, the affected spots shift by a day and the next forecast corrects for it. No special handling is needed.
- **Shortages are accepted.** If no suitable car is available, the spot waits and rolls forward. Since this is a closed system and the forecast keeps counting waiting spots, shortages correct themselves quickly, usually by the next day.

## 11. Daily Sequence

Strictly sequential: each step finishes before the next starts. The main is needed for yard work, and there aren't enough arrival and departure tracks to overlap steps.

| Step | Event | Who | Signal |
|---|---|---|---|
| 0 | **Pre-session chores:** rebuild the westbound manifest in the East loop (re-sorted using the yard tracks) and the eastbound manifest in West staging, and make the engine moves | Operator, from the chore sheets | West chore done; East chore done |
| 1 | Westbound manifest leaves the East loop and arrives at the yard, holding on the main | Road crew | none (implied) |
| 2 | **Switcher job A:** cut the rear Local block and shove it into the Locals track; pick up the Westbound track and add it to the rear | Yard switcher | A done |
| 3 | Westbound manifest runs to West staging | Road crew | none (implied) |
| 4 | **Local job:** spot and pull at each industry; on return, leave the returned cars on the main | Local crew | Each pull done; each set-out done; **local back in yard** |
| 5 | **Switcher job B:** sort the local's returned cars onto Eastbound, Westbound or Locals, and return any undelivered cars to Locals | Yard switcher | B done |
| 6 | Eastbound manifest leaves West staging and arrives at the yard (only after job B is finished) | Road crew | none (implied) |
| 7 | **Switcher job C:** cut the rear Local block into the Locals track; pick up the Eastbound track and add it to the rear | Yard switcher | C done |
| 8 | Eastbound manifest runs into the East loop and sits there overnight | Road crew | none (implied) |
| — | **Session complete = day advance** | Operator | Session complete |

Results of this order:
- Cars set out from the westbound manifest can be spotted **the same day**. That includes refilling spots the local empties today, because those spots are known in advance.
- Cars set out from the eastbound manifest are spotted **the next day**.
- The westbound pick-up block holds **yesterday's** local pulls. The eastbound pick-up block holds **today's**.
- The East loop empties at step 1 and fills at step 8, so it never needs room for two trains.
- **If the local has no work on a given day,** the software skips the local job and its "local back in yard" signal automatically.

## 12. Session Work Lists

The software produces five kinds of list each session, shown on the web page (Section 15). Chore sheets can also be printed. The chore sheets, job A and the local's list are produced at the day advance. **Job B's list is produced only when the local signals it is back in the yard**, and **job C's pick-up block is final only once B is done**, because both depend on what the local actually did.

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
                                                       [ West chore done ]

EAST LOOP — Westbound manifest
1. Engines from storage → staging:  none
2. Engines from staging → storage:  CSX 3150
3. Train list
   ...
                                                       [ East chore done ]
```

Load and destination appear only on Local-block cars.

### 12.2 Switcher jobs A and C (one per manifest)
```
WESTBOUND MANIFEST — switcher
1. Cut the rear 3 cars → shove into Locals track:
     GATX 7721 tanker, CSXT 14420 boxcar, ATSF 5521 boxcar
2. Pick up from Westbound track → add to rear:
     UP 41230 hopper, BNSF 72281 boxcar
(Train now 22 cars — exception overload train)   — shown only when over 20
                                                       [ A done ]
```

### 12.3 Local job (by industry)
The local takes **specific** cars from the Locals track. The order of cars in the local train doesn't matter. Each move has its own signal; moves at different industries can be done in any order. Where a spot has both, its set-out unlocks only after its pull is done.
```
INDUSTRY #1
  Pull  BNSF 72281 (boxcar, loaded)  ← Loading door 2           [ done ]
  Spot  CSXT 14420 (boxcar, empty)   → Loading door 1           [ done ]
TRANSFER FACILITY
  Pull  TILX 30018 (tanker, empty)   ← Tank car unloading       [ done ]
  Spot  GATX 7721 (tanker, loaded)   → Tank car unloading       [ done ]  (after pull)
                                                       [ Local back in yard ]
```

### 12.4 Switcher job B (sorting the local's returned cars)
Built from what actually happened: every car the local pulled, plus every car it didn't deliver.
```
YARD JOB — sort local's returned cars (on the main)
  → Eastbound track:  BNSF 72281 boxcar (loaded)
  → Westbound track:  UP 41230 hopper (loaded)
  → Westbound track:  TILX 30018 tanker (empty, returning to West staging)
  → Locals track:     ATSF 5521 boxcar (empty, held for reuse)
  → Locals track:     GATX 7721 tanker (loaded, not delivered, retry next run)
                                                       [ B done ]
```

## 13. Signals and Session Flow

### Signals
| Signal | Job | Effect on the records |
|---|---|---|
| West chore done / East chore done | Step 0 | Eastbound manifest built in West staging; westbound manifest built in the East loop; engine moves applied |
| A done | Step 2 | Westbound Local block → Locals track; Westbound track pick-up → westbound manifest; manifest → West staging (step 3 implied) |
| Pull done (per spot) | Step 4 | Car from spot → local; spot → COOLDOWN or EMPTY_AWAITING_CAR |
| Set-out done (per spot) | Step 4 | Car from local → spot; assigned spot cleared; spot → PROCESSING |
| Local back in yard | Step 4 | Local closed; any set-out not signalled = **not delivered**; job B's list produced |
| B done | Step 5 | Returned cars → Eastbound / Westbound / Locals; undelivered cars → Locals (still assigned); job C's list finalized; eastbound manifest at the yard (step 6 implied) |
| C done | Step 7 | Eastbound Local block → Locals track; Eastbound track pick-up → eastbound manifest; manifest → East loop (step 8 implied) |
| Session complete | Day advance | Counters and countdowns advance, day-early rolls made, next session's lists produced |

- **Chores and yard jobs are binary:** done or not done. There is no partial completion. If something physically went differently, the operator fixes the record with the edit tool (Section 14).
- **Only the local has per-move signals:** one per pull and one per set-out.
- **No signal means it didn't happen.** A car not signalled as pulled is still on its spot (the spot stays READY_FOR_PICKUP, with its destination kept). A car not signalled as set out is still on the local, and job B returns it to the Locals track.
- **Cars for the local are on the local once job A is done.** From that point the local's set-out cars are recorded as being on the local train.
- **Signals are taken in sequence order.** The software always shows the current job. A signal for a later job while an earlier one is still pending is refused with a "waiting on …" message. The two chores can be done in either order, and the local's moves in any order.

### Session complete and pausing
- **A session ends only when the operator signals "session complete."** Powering off, or simply stopping for the day, is a **pause**. On power-up the software resumes at the current job, with every car and spot exactly where the signals left them.
- **"Session complete" is the day advance.** There is no separate correction step before it, because corrections can be made at any time (Section 14).
- **Session complete is accepted only when every chore and yard job (A, B, C) is done.** The trains must clear the main and reach their worlds anyway, and since a session can be paused indefinitely there is never a reason to abandon a yard job. The local is the only job that can leave work undone, and job B cleans up after it.

## 14. Corrections, Persistence and Roster Maintenance

- **Edit tool, available at any time:**
  - **Cars:** set any car's actual location (track, spot, train or world) and load, for example to fix a wrong car spotted or a record found out of step with the layout.
  - **Spots:** set a spot's state directly, for example force it back to EMPTY_AWAITING_CAR. You can also set its days left, its outgoing destination and its pattern position. This lets you correct a car and its spot together, so a car correction never leaves a spot in the wrong state.
  - **Undoing a signal:** the edit tool is also how a wrongly pressed signal is undone. Undo is never done from the physical buttons.
- **Persistence:** every signal and every edit is saved the moment it happens. Turning the system off at any point loses nothing.
- **Cold start**, done once or after a deliberate reset:
  1. **Import the roster from two CSV files.** The car file lists each car's mark, number, type and location, which says whether it is physically in East staging (the loop) or West staging. The engine file lists each engine's mark, number, model, pool and location (Storage, East staging or West staging). The formats are in Section 16.
  2. Every spot and yard track starts empty, and the industries fill up over the first few sessions.
  3. The software produces the first session's lists.
- **Roster changes**, made on the web page with no reset needed:
  - A new car is added into a world.
  - A retired car is removed wherever it is. If it was on a spot or assigned to one, correct that spot with the edit tool.
- **No backups and no history.** If the state is lost, do a cold start.

## 15. Platform

- **The main program runs on a Raspberry Pi:** Python, with SQLite for the saved state.
- **It serves a web page over Wi-Fi.** Any device with a browser can use it. The first one will be an **old Android tablet**, used purely as a browser. The page should be plain HTML with very little JavaScript, so older Android browsers can handle it. The page shows spot states, the current job, all work lists, the signal buttons and the edit tool.
- **Every signal goes through one input layer.** The core program doesn't know or care where a signal came from. The web page is the first input. Later, ESP32 nodes with push buttons and small LCDs (talking to the Pi over MQTT) plug into the same layer.
- **The long-term goal is for the LCDs and physical buttons to be the main way signals are sent**, with the tablet as a companion for detail and corrections. The hardware design itself (nodes, button layout, what each LCD shows) is still to be done, but it is no longer blocking: it only needs to send the signals in Section 13 and show spot states and the current job.

## 16. Data Model

The model **stores decisions and current positions only. Everything else is worked out when it is needed.** That way a list can never drift out of step with the records: after an edit, every list is simply correct the next time it is shown.

**Plain language everywhere.** Several operators will use the system, so every value a person reads or types uses plain words, never single letters or codes. That applies to the configuration file, the CSV files, the web page, the printed sheets and the database itself. For example: "East staging", not "E"; "Westbound manifest", not "WB"; "not tracked", not "n/a". Spots and industries are always shown by their `name`, never by their internal id. Words typed into a file are matched without regard to capitals.

### 16.1 Configuration: a YAML file
The configuration never changes while the system runs. It is a file you edit by hand and keep in git, for example `config.yaml`:

```yaml
settings:
  hold_days_on_locals: 2           # N, Section 8
  eastbound_length_min: 12         # Section 9
  eastbound_length_max: 20
  train_nominal_max: 20            # above this = exception overload train
  three_engines_from: 16           # cars; 15 or fewer = 2 engines
  capacity:
    east_staging: 30               # the hidden return loop
    west_staging: 70               # both car tracks together (pool)
    yard_track: 35

industries:
  - id: industry_1
    name: "Industry #1"
    spots:
      - spot_id: industry_1_door_1
        name: "Loading door 1"
        requirement_mode: fixed
        car_type: boxcar
        direction: outgoing
        pattern: [East, East, West]
        disruption_chance: 0.1
        base_processing_days: 2
        delay_chance: 0.1
        cooldown_days: 0
      # ... further spots; random-mode spots use possible_requirements (Section 5)
```

- **All settings are changed in this file,** including the Eastbound length range and every capacity. The values shown are the defaults.
- **The spot fields are exactly the Section 5 schema, minus `position`.** `position` is runtime state, so it lives in the database.
- **Reloading the configuration:**
  - A spot that is new in the file gets a fresh state row (EMPTY_AWAITING_CAR).
  - A spot removed from the file is reported, and its state is ignored.
  - If a pattern gets shorter, its position wraps around.
- **Car types are plain text.** A car serves a spot when its type matches the spot's `car_type` exactly.

### 16.2 State: SQLite, five tables
The program is written in Python, using the standard `sqlite3` module and no ORM. **Each signal and each edit is one complete database transaction.**

| Table | Fields | Notes |
|---|---|---|
| `session` (one row) | day number; done flags: West chore, East chore, job A, local back, job B, job C; local has work today | The current job is worked out from the flags |
| `car` | id, mark, number, type, location (`loc_kind`, `loc_ref`), `seq`, load, last loaded at industry, origin world, assigned spot, destination world, days held on Locals | Mark + number is unique. **Destination world** is set when a loaded car is pulled from an outgoing spot, so job B knows where it goes |
| `engine` | id, mark, number, model (optional), pool (local / switcher / manifest), location, `seq` | |
| `spot_state` | spot id, state, days left (processing or cooldown), pattern position, current random requirement (which one + rolled direction), outgoing destination, waiting since day, next delay roll, next random requirement | **Waiting since day** drives oldest-first priority. The **next** fields are the day-early rolls (Section 5) |
| `consist_plan` | train (Westbound manifest / Eastbound manifest / Local), seq, car or engine | Written at the day advance. Applied by the matching signal: West chore done, East chore done, or job A done for the Local. Cleared at the next day advance |

### 16.3 Locations
Cars and engines use the same location scheme:

| `loc_kind` | `loc_ref` | `seq` means |
|---|---|---|
| `world` | East staging, West staging | not used |
| `yard` | Eastbound track, Westbound track, Locals track | order of arrival (oldest first, for the capacity fallback in Section 9) |
| `spot` | the spot (shown by its name) | not used |
| `train` | Westbound manifest, Eastbound manifest, Local | position, head to rear; engines lead first |
| `storage` | Storage (engines only) | not used |

- **East staging is the hidden return loop.** That is its name in every list and value.

- **West staging is a pool.** The software doesn't track which staging track a car is on. Cars are found by number.
- **A train exists only from its chore signal until it arrives.** When it arrives, its cars and engines become part of that world. The local's train exists from A done to B done.

### 16.4 Worked out when needed, never stored
- **Local block:** the cars in a manifest that have an assigned spot.
- **Job A and C pick-ups:** the whole Westbound or Eastbound track at the time of the job. Job C's provisional list is a prediction of that track.
- **Local list:** pulls are the READY_FOR_PICKUP spots. Set-outs are the cars assigned to spots.
- **Job B:** the routing rules in Section 8, applied to the cars on the local when it is back in the yard.
- **Engine moves on the chore sheets:** the planned consist compared with where the engines are now.
- **Also worked out:** spot display text, the forecast, and the capacity and length checks.

### 16.5 Cold-start CSV files
```
cars.csv      mark,number,type,location        location = East staging or West staging
engines.csv   mark,number,model,pool,location  pool = local, switcher or manifest
                                              location = Storage, East staging or West staging
```
Example rows:
```
cars.csv      CSXT,14420,boxcar,West staging
engines.csv   BNSF,7710,ES44AC,manifest,Storage
```
Every column is required except `model`, which can be left empty if unknown.

## 17. Still Open

- **Industry configuration:** spot counts and settings for Industries #1–3, and whether Industry #4 is built. This is data, not design. The software is driven by configuration, so building can start without it, but it is needed before the first real session.
- **Hardware design** for the LCD and button nodes (Section 15). Not blocking.
- **The Android tablet's version**, to confirm the web page works on its browser. Minor.

## 18. Considered and Rejected

| Idea | Why it was dropped |
|---|---|
| Randomizing the daily train schedule (order and/or number of trains) | The fixed daily sequence works well |
| Weekday vs. weekend (or other repeating) schedule variants | Same |
| Adding extra empties to arrivals to relieve outgoing shortages | Already covered: worlds supply empties for outgoing spots (Section 8) |
| A capacity warning on the Locals track | It holds over 30 cars and the local runs 7–10 |
| JMRI Operations; a spreadsheet | See Section 1 |

## 19. Decision History (superseded ideas, for reference)

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
| (1.1) Every job assumed done; all moves applied at day advance; corrections by skipping jobs | Live signals; records change per signal; no signal = didn't happen | Records follow the layout; a skipped move updates later jobs (B, C) correctly |
| (1.1) Records saved only at day advance | Every signal and edit saved immediately; sessions can pause across power-off | Pick up exactly where play stopped |
| (1.1) Separate correction step, then day advance | "Session complete" is the day advance; edits allowed any time | Records are live, so no batch correction is needed |
| (1.1) Ending a session early by skipping the remaining jobs | Pausing; session complete requires all yard jobs done | Nothing needs to carry over between sessions |
| (1.1) Job B's list known before the session | Produced when the local is back in the yard; includes undelivered cars | It depends on what the local actually did |
| (1.1) Outgoing destination decided when the car is pulled | Fixed when processing completes | A car that isn't pulled keeps its destination |
| (1.1 open) Empties for outgoing spots from East, West or either | Held Locals empties first, then the world the load will ship to (shuttle model) | Cars shuttle between a layout industry and an unseen industry in one direction |
| (1.1 open) Printed lists and/or a web page | Web page served by a Raspberry Pi; tablet first, LCDs and buttons later | Any device can use it; hardware plugs into one input layer |
| (1.2) Eastbound length matched to the westbound arrival in West staging | A random length of 12–20 cars leaving West staging, raised to the train's minimum | Variety; West staging capacity is still checked |
| (1.2) Hard 20-car limit; pick-up overflow left behind, oldest first | 20 is the normal size; whole pick-up blocks always go; an exception overload train is allowed | Overflow is rare and small; the destinations have room |

---

## Appendix A — Machine-Readable Spec (AI-facing)

```yaml
spec: digital-train-operations
version: "1.4"
date: 2026-11-09
supersedes: [full-spec_v1.3.md, full-spec_v1.2.md, full-spec_v1.1.md, checkpoint_7-13-26.md, delta_11-06-26.md]
resume_instruction: "Read this appendix only; main body = human prose of same content."
next_version: "1.5 (new file digital-train-operations-full-spec_v1.5.md)"
changes_from_1.3: [data model added (section data_model), cold start via CSV import, roster add/retire via web page, edit tool can set spot state, W staging = pool only (no per-track tracking), plain-language values everywhere (no single letters/codes)]
changes_from_1.2: [EB length random 12-20 leaving W (replaces W_balance), pickup blocks never left behind, exception overload train, 20 = nominal not hard cap, confirmed local blocks demand-driven + WB non-local cars all continue W]
user_style: "Dictates via speech-to-text; literal 'Period.'/'comma'/'colon' words are punctuation artifacts."
plain_language_rule: "HARD RULE (user, 2026-11-09): every value a person reads or types (config YAML, CSV, web page, printed sheets, DB values) uses plain words, never single letters/codes. E->'East'/'East staging', W->'West'/'West staging', WB/EB->'Westbound manifest'/'Eastbound manifest', LOCAL->'Local', n/a->'not tracked'. Spots/industries shown by name, never id. Typed values matched case-insensitively. Shorthand in THIS appendix is AI-facing only."
status: "design + data model complete except industry config data + hardware node design (non-blocking). Next: first code."

philosophy:
  scope: digitize ops paperwork; no train-movement automation
  car_tracking: individual (roster)
  build: custom (JMRI rejected: no demand planning, spot mechanics, industry jobs, button fit; spreadsheet rejected)
  history: none; state = current only
  confirmation: live signals; records follow layout per signal

prototype:
  framing: modern-era crew-change point + small yard, single-track secondary main, based local
  trains_per_day: {manifest_EB: 1, manifest_WB: 1, local: 1}  # fixed; schedule variation rejected
  through_trains: none  # through-only car types ride as continuing cars in manifests
  manifests: arrive presorted; Local block at REAR; switcher does all set-out/pick-up; road crews never switch
  power_realism: modern 6-axle OK on local/yard
  worlds_meaning: "distant places (e.g. yard=Chicago, W=Seattle); cars shuttle layout industry <-> implied industry in one direction"

layout:
  orientation: {W: left, E: right}
  main: single track; passing sidings exist; yard switching on main OK (<=2 operators)
  industries: {ind1: built, ind2: built, ind3_transfer: built, ind4: uncertain}
  spurs: ind1/ind2 shared lead and ind3, all diverge toward W; aux yard near ind1/2 gives runarounds
  yard: {tracks: [Eastbound, Westbound, Locals], type: stub, ladder: W end, cap_each: 30-35}
  locals_track_capacity_check: none  # >30 cars; local expected 7-10 cars
  engine_storage: 3 tracks
  world_E: {type: hidden_return_loop, built: true, capacity_trains: 1, cap: "~30 cars+3 eng", overnight: true}
  world_W: {type: stub_staging, built: false, tracks: 3, car_tracks: 2, cap_each: 30-35, engine_escape: "1 track + transfer table at stub end", visible_reachable: true}
  max_train: {cars_nominal: 20, engines: 3, overload_allowed: true, hard_limits: "E loop ~30 cars; W staging capacity"}

roster:
  car_fields: [mark, number, type, location, load(loaded|empty|not tracked), last_loaded_at_industry, origin_world(East staging|West staging), assigned_spot(nullable), days_held_on_locals, dest_world(nullable; set on pull of loaded car from outgoing spot)]
  location_values: see data_model.locations
  any_car_type_can_serve_industry: true  # role from config; unused types = through-only
  engine_groups:
    local_pool: {per_train: 2, pick: random}
    switcher: {count: 1, dedicated: true}
    manifest_pool: {size: ~14, per_train: "2 if len<=15 else 3 (overload always 3)", len_basis: "max(arriving, departing)", eligible: "engines at that world + storage", pick: random}
  engine_shortage: not modeled (ample)

spots:
  capacity: 1 car
  schema: "all: spot_id (internal), name (shown); fixed: car_type,direction,source|pattern,position,disruption_chance,base_processing_days,delay_chance,cooldown_days; random: possible_requirements[car_type,direction,source_weights|destination_weights,weight,base_processing_days,delay_chance,cooldown_days]; direction values East|West"
  states: [EMPTY_AWAITING_CAR, PROCESSING, READY_FOR_PICKUP, COOLDOWN]
  transitions:
    EMPTY->PROCESSING: on setout_done signal
    PROCESSING->READY: at day advance when countdown done; outgoing dest fixed here (pattern[position] + disruption roll | rolled dest); position advances here
    READY->COOLDOWN_or_EMPTY: on pull_done signal
    COOLDOWN->EMPTY: at day advance; random spot draws new requirement at EMPTY
  display: plain-language state per spot = visible demand signal (web now, LCD later); e.g. "needs loaded boxcar from East [— CSXT 14420 waiting on Locals]"
  incoming: needs loaded car of type from source dir; pulled -> empty
  outgoing: needs empty; pulled -> loaded, dest already fixed at READY
  position: advances every completion unconditionally (incl disruption)
  delay: rolled daily, uncapped stacking
  cooldown: fixed days
  random_mode: no position; fresh E/W roll per draw; draw at EMPTY
  preroll: delay rolls + random draws (incl source/dest) done ONE DAY AHEAD -> exact forecast; always applied to ACTUAL spot state (skipped move = timeline shifts 1 day)
  shortage: oldest-waiting first, random tiebreak; unserved stays EMPTY, rolls forward
  local_visit: one per industry per day, pull+spot combined
  pull_before_setout: setout on an occupied spot only after its pull_done; separate signals (pull alone OK if no replacement car)
  config_vs_state: config static; runtime state persists, never reset on reload

worlds:
  rebuilt: before every session (chore)
  loads_inside: not tracked
  E: closed set = exactly cars of prior EB manifest; re-sorted via yard tracks, never mixed with yard cars; nothing added/removed; all ride out; rebuild ends with train back in loop for step 1 (CONFIRMED)
  W: pool; EB built from any staging cars; rest stay as spares; WB arrival couples onto spares OK

loads:
  tracked_only_for: local-bound/local-originated cars; continuing + world cars = not tracked
  assign_at: Local-block selection; incoming spot -> loaded; outgoing spot -> empty
  undelivered: keeps assigned load
  return_to_shipper: if target industry == last_loaded_at -> must be empty (outgoing spot only)
  pulled_cars: keep real load on Eastbound/Westbound tracks; -> not tracked on entering world

supply_to_spots:
  incoming: loaded car from spot's source world (fixed source | rolled source)
  outgoing_empty:
    1: held empty of type on Locals track first, any origin (CONFIRMED)
    2: else from world == scheduled destination (shuttle): dest W -> empty from W staging (EB local block); dest E -> empty from E loop (WB local block)
    scheduled_dest: "fixed: pattern[position] (pre-disruption); random: dest rolled at draw"
    disruption: rolled at completion; may ship to other side than supplied from; accepted
  undelivered_car: back to Locals via job B, keeps assigned_spot, first in line next run; forecast counts spot as covered

routing_pulled_cars:
  loaded_from_outgoing: Eastbound|Westbound track per dest fixed at READY
  empty_from_incoming:
    if_type_used_by_any_outgoing_spot: hold on Locals up to N days (default 2, configurable; counted per day advance), then -> track toward origin_world
    else: immediately -> track toward origin_world

train_building:
  local_blocks_demand_driven:  # CONFIRMED 2026-11-09; computed at day advance from forecast, net of held empties + undelivered cars on Locals
    WB_block: serves TODAY's E-supplied demand (set out step 2, spotted same day)
    EB_block: serves TOMORROW's W-supplied demand (set out step 7, spotted next day)
  local_block: rear; filled from ANY matching-type car available in that world (prior role irrelevant)
  continuing: random order ahead of local block
  WB_continuing: all WB cars not in local block continue to W staging (job A cuts local block only)  # CONFIRMED 2026-11-09
  WB_length: fixed = E closed set (yesterday's EB arrival in E)
  EB_length:  # replaces v1.2 W_balance
    draw: random int [eb_len_min, eb_len_max], config defaults 12, 20; counted LEAVING W staging (before yard work)
    floor: local_block + tomorrow's E-supply cars not covered by Eastbound pickup; draw raised to floor
    cap: W staging cars available (shortage rules if below floor)
    continuing_pick: random from W pool; unchosen stay as spares
    W_capacity: hard check retained
  E_supply: EB (+ its Eastbound pickup) must carry cars for TOMORROW's E-supplied demand (E-sourced incoming loads + empties for outgoing spots scheduled to ship E not covered by held empties)
  post_yard_length: "arriving - setout + pickup"; ENTIRE pickup track always taken (jobs A and C); >20 -> exception overload train (expected rare, 1-2 cars)
  overload_propagates: EB overload -> next day's WB same size (E closed set); WB may exceed 20 after job A too; same rule
  overflow_safeguard: only if E loop (~30) or W staging capacity would be exceeded -> oldest pickups first, rest wait; not expected
  leftover_engines: both worlds -> storage at chore

forecast:
  E_supplied_for_day_D: chosen from cars sent E on day D-1 EB; set out D step2 before local -> same-day spot
  W_supplied: EB set out at step7 after local -> spotted next day
  direction: incoming = source; outgoing (no held empty) = scheduled destination
  inputs: industry config + spot state + assigned/undelivered cars + prerolls; no extra config
  assumes: today's local completes all listed moves; deviations self-correct next forecast
  shortages: accepted; self-correct ~next day

daily_sequence:  # strictly sequential, no overlap
  0: pre-session chores (rebuild WB in E loop via yard tracks; rebuild EB in W staging; engine moves)  [signals: chore_W_done, chore_E_done; either order]
  1: WB leaves E loop -> yard (holds on main)  [implied]
  2: switcher job A: cut rear Local block -> Locals; pick up Westbound track -> rear  [A_done]
  3: WB -> W staging  [implied by A_done]
  4: local job; leaves returned cars on main  [pull_done(spot), setout_done(spot), local_back]; auto-skipped if no local work
  5: switcher job B: sort returned cars -> Eastbound|Westbound|Locals; undelivered -> Locals  [B_done]
  6: EB leaves W staging -> yard (only after 5 done)  [implied by B_done]
  7: switcher job C: cut rear Local block -> Locals; pick up Eastbound track -> rear  [C_done]
  8: EB -> E loop, overnight  [implied by C_done]
  end: session_complete == day advance
  facts: WB pickup = yesterday's pulls; EB pickup = today's pulls; E loop empty at 1, filled at 8

signals:
  input_layer: single entry point for all signals; sources = web page now, ESP32/MQTT later; core agnostic
  chore_and_yard_jobs: binary done/not-done, no partial
  local: per-move pull_done / setout_done (per spot) + manual local_back by local operator
  no_signal: didn't happen (unpulled car stays on spot, READY, keeps dest; unset-out car stays on local -> job B returns it to Locals)
  local_cars_on_local_from: A_done
  local_back: closes local; unsignalled setouts = not delivered; generates job B list
  B_done: applies sort; finalizes job C pickup list
  ordering: accepted only in sequence; later-job signal while earlier pending -> refused "waiting on <job>"; chores either order; local moves any order (subject to pull_before_setout)
  session_complete: requires chores + A + B + C done (local may have undone moves); performs day advance (countdowns, held-days counters, day-ahead rolls, next lists)
  pause: power-off/stop anytime = pause; resume at current job with exact state

outputs:
  produced_at_day_advance: [chore sheets, job A, local list, job C provisional]
  produced_live: {job_B: on local_back, job_C_pickup_final: on B_done}
  medium: web page (primary); chore sheets printable
  chore_sheet_per_world: ["1 engines storage->staging", "2 engines staging->storage", "3 train list: engines lead-first; cars head->rear; local-block cars show load+dest"]; empty section prints "none"
  switcher_A_C: ["cut rear N cars (listed) -> Locals", "pick up <dir> track (listed, entire track) -> rear", "note if >20: exception overload train"]
  local: per industry, per move with done button: "Pull <car> <- <spot>" / "Spot <car> -> <spot>"; specific cars; train order irrelevant; setout unlocks after pull on same spot
  switcher_B: per car -> Eastbound|Westbound|Locals (with reason: loaded dest / empty to origin / held / not delivered, retry next run)

corrections_persistence:
  edit_tool: anytime; set car location + load; set spot state (state, days_left, out_dest, position); also undoes mistaken signals; never via physical buttons
  persist: every signal + edit saved immediately (SQLite), one transaction each
  cold_start: once or on reset; import cars.csv + engines.csv (formats in data_model); spots+yard empty; generate first session lists
  roster_changes: via web page; add new car into a world; remove retired car anywhere (fix its spot via edit tool if needed)

data_model:
  principle: store decisions + current positions only; derive everything else on demand (lists never drift)
  impl: Python, stdlib sqlite3, no ORM
  config:  # YAML file (e.g. config.yaml), hand-edited, in git, static at runtime
    settings: {hold_days_on_locals: 2, eastbound_length_min: 12, eastbound_length_max: 20, train_nominal_max: 20, three_engines_from: 16, capacity: {east_staging: 30, west_staging: 70, yard_track: 35}}
    industries: "[{id, name, spots: [section-5 spot schema minus position; spot_id internal, name shown]}]"
    reload: new spot -> fresh state row (EMPTY); removed spot -> reported, state ignored; shorter pattern -> position wraps
    car_types: free text; exact match car.type == spot car_type
  tables:
    session: "single row: day, west_chore_done, east_chore_done, job_a_done, local_back, job_b_done, job_c_done, local_has_work; current job derived from flags"
    car: "id, mark, number (unique mark+number), type, loc_kind, loc_ref, seq, load, last_loaded_industry, origin_world, assigned_spot, dest_world, days_held"
    engine: "id, mark, number, model(opt), pool(local|switcher|manifest), loc_kind, loc_ref, seq"
    spot_state: "spot_id, state, days_left, position, req_index, req_dir, out_dest, waiting_since_day, next_delay, next_req_index, next_req_dir"
    consist_plan: "train(Westbound manifest|Eastbound manifest|Local), seq, car_id|engine_id; written at day advance; applied by west_chore/east_chore/job_a done; cleared next day advance"
  locations:  # shared by car + engine; values are plain language
    world: {ref: [East staging, West staging], seq: unused, note: "East staging = hidden return loop"}
    yard: {ref: [Eastbound track, Westbound track, Locals track], seq: arrival order (oldest first)}
    spot: {ref: spot_id (displayed by spot name), seq: unused}
    train: {ref: [Westbound manifest, Eastbound manifest, Local], seq: "head->rear; engines lead first"}
    storage: {ref: Storage, engines_only: true}
    W_staging: pool only; no per-track tracking  # CONFIRMED
    train_lifetime: "manifest: chore signal -> arrival (dissolves into world); LOCAL: A_done -> B_done"
  derived_not_stored: [local block = manifest cars with assigned_spot, job A/C pickup = whole track at job time (C provisional = prediction), local list = READY spots + assigned cars, job B routing (section 8 rules), chore-sheet engine moves = plan vs current location, spot display text, forecast, capacity/length checks]
  csv:
    cars: "mark,number,type,location  (location East staging|West staging)"
    engines: "mark,number,model,pool,location  (pool local|switcher|manifest; location Storage|East staging|West staging)"
    required: all columns except engine model (may be empty)
    example: ["CSXT,14420,boxcar,West staging", "BNSF,7710,ES44AC,manifest,Storage"]
  backups: none (loss -> cold start)

platform:
  brain: Python on Raspberry Pi
  db: SQLite
  ui: web page served over Wi-Fi; any browser; first client = old Android tablet (browser only); plain HTML, minimal JS
  ui_contents: spot states, current job, work lists, signal buttons, edit tool
  future: ESP32 nodes + push buttons + LCDs over MQTT become PRIMARY signal input; tablet = companion
  hardware_design: TBD, non-blocking (must send Section-13 signals; show spot states + current job)

open:
  - industry configs (spot counts ind1-3; ind4 existence) — data, needed before first real session, not before coding
  - hardware node design — non-blocking
  - Android tablet OS version (browser compatibility) — minor

rejected:
  - v2 random daily schedule (order/count)
  - v2 weekday/weekend schedule variants
  - demand-aware arrival injection (superseded by worlds supplying empties)
  - Locals track capacity warning
  - JMRI, spreadsheet

confirmed_2026-11-08:  # were derived; user confirmed
  - strict signal ordering (later job refused while earlier pending)
  - local's set-out cars count as on the local from A_done
  - job C pickup list finalized at B_done (EB arrives after B_done in practice and by sequence)
  - outgoing dest uses pre-disruption pattern entry for empty sourcing; disruption still rolled at completion

confirmed_2026-11-09:
  - local blocks demand-driven (WB = today's E demand, EB = tomorrow's W demand)
  - all non-local WB cars continue to W staging
  - EB length random 12-20 leaving W staging, floor = local block + uncovered E-supply cars
  - pickup blocks never left behind; >20 = exception overload train; applies to WB too

confirmed_2026-11-09_data_model:
  - data model as proposed (YAML config + 5 SQLite tables + derive-on-demand)
  - W staging pool only
  - cold start via CSV; single add/retire via web page
  - edit tool can set spot state
  - eb_length_min/max are config settings (defaults 12/20)
  - overflow_safeguard (oldest-first leave-behind) only at destination capacity limits; expected almost never
  - engines.csv location column required: Storage|East staging|West staging (no blank default)
  - capacities are config settings (defaults east_staging 30, west_staging 70, yard_track 35)
  - plain-language rule (see plain_language_rule)
  - spot `name` field in config for display
  - typed values matched case-insensitively
  - engine model may be empty in CSV

derived_not_explicitly_confirmed: none
```
