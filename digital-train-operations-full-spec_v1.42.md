# Digital Train Operations — Full Design Specification

**Version 1.42 — 2026-11-11**

This document is the complete design for the Digital Train Operations project as of this version. It replaces version 1.41 (`digital-train-operations-full-spec_v1.41.md`) and all earlier working files, which are kept only for history. Where they disagree with this document, this document wins.

The main body is written to be read by a person. **Appendix A** is a compact, machine-readable version of the same design for use by an AI assistant when resuming work.

**What changed since 1.41:** coding has started. Steps 1–5 of the development plan are built and tested (Section 17), and the decisions made while building them are folded in:
- **"Idle" replaces "cooldown"** everywhere, including the configuration field, now `idle_days`.
- **All plain words are sentence case:** "Awaiting car", "Ready for pickup", "Loaded", "Not tracked" and so on (Section 16).
- **A new setting, `delay_chance_max`,** caps every spot's delay chance (Section 5).
- **Spot timing is spelled out** (Section 5): how delays, processing days and idle days count, and how the day-early rolls work.
- **Configuration changes:** changing which industries and spots exist, or what a spot needs, requires a cold start. Tuning changes don't (Section 16.1).
- **Configuration checks:** optional fields and their defaults, limits on values, and unique names (Section 16.1).
- **Roster changes never need a cold start.** A "Sync roster" action applies edits made to the roster files. A car retired while it sits at a spot becomes a **Bad order** car that the local pulls and sends to West staging (Section 14).
- **Python 3.13**, to match the current Raspberry Pi OS (Section 17).

Version 1.41 had added the development plan. Version 1.4 had added the data model. See Section 20 for the full history.

---

## 1. Purpose and Philosophy

The project digitizes **operations** on an N scale model railroad. It does not automate train movement: there is no DCC or dispatcher automation. The software replaces car cards and waybills by generating each session's work automatically, driven by the needs of the industries.

- **Every car is tracked individually.** There is a roster of specific numbered cars and engines, and the software always knows where each one is. (This reverses an earlier decision to track only car types. The physical layout requires it: what returns from a hidden loop is exactly what went in.)
- **The operator confirms work as it happens.** The software's records follow the layout through signals (Section 13), not through one bulk update at the end of the session.
- **The software is a custom build.** JMRI Operations was considered and rejected. Even with individual car tracking, JMRI lacks demand-driven planning, the spot mechanics described here (processing delays, disruptions, patterns, idle periods, oldest-first priority), jobs organized by industry, and an easy fit with physical confirmation buttons. A spreadsheet-based approach was also rejected.
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
- Reporting mark (always stored in capitals) and number, and car type. **A car's type never changes.**
- **Location:** a world (East loop or West staging), a yard track, a spot at an industry, or in a train (westbound manifest, eastbound manifest, or the local).
- **Load status:** Loaded, Empty or Not tracked. It is Not tracked for continuing cars and for any car in a world; there, load status is irrelevant.
- **Last industry that loaded it.** Used by the return-to-shipper rule (Section 7).
- **The world it arrived from** (East or West). Set when it is set out from a manifest, and used to send unwanted empties back (Section 8).
- **Assigned spot**, if any. Set when the car is chosen for a Local block; cleared when its set-out is signalled done. A car that wasn't delivered keeps its assigned spot (Section 8).
- **Days held on Locals**, for empties waiting there for reuse (Section 8).
- **Destination world**, for a loaded car pulled from an outgoing spot. It carries the destination fixed when the spot became Ready for pickup (Section 5) so job B can route the car.
- **Bad order:** set when the car is retired while it sits at a spot (Section 14). The local pulls it, and it leaves the roster when it reaches West staging.

**Any car type can serve an industry.** A car's role comes entirely from the industry configuration. Types that no spot uses (for example steel coil cars) automatically act as through traffic only.

### Engines
Engines belong to one of three groups:

| Group | Use | Size |
|---|---|---|
| Local pool | The local always runs with **2** engines, chosen at random from this pool | Several engines |
| Yard switcher | One **dedicated** engine | 1 |
| Manifest pool | Manifests run with 2–3 engines (Section 9) | About 14 engines |

There are more than enough engines for this model, so engine shortages are not planned for. To guarantee that, the engine roster must always have at least **1 switcher, 2 local engines and 6 manifest engines** (both manifests can need 3 each). A cold start or roster sync that would leave fewer is refused.

## 5. Industries and Spots

An **industry** is a name plus a list of **spots**. All behavior lives in the spots, so there are no special industry types. The transfer facility is just an industry with some fixed spots and one random spot. **A spot holds one car.**

### Spot schema

```json
{
  "spot_id": "...",                  // internal key, never shown to operators
  "name": "Loading door 2",          // what operators see in every list and display
  "requirement_mode": "Fixed | Random",

  // --- FIXED MODE ---
  "car_type": "...",
  "direction": "Incoming | Outgoing",
  "source": "East | West",           // incoming only: which direction the loaded car comes from
  "pattern": ["East", "East", "West"], // outgoing only: ordered, repeating destination list
  "disruption_chance": 0.0,          // outgoing only: chance per completion to flip the pattern's destination
  "base_processing_days": 2,
  "delay_chance": 0.0,               // rolled every processing day; must be below 1
  "idle_days": 0,                    // fixed, no variance

  // --- RANDOM MODE ---
  "possible_requirements": [
    {
      "car_type": "...",
      "direction": "Incoming | Outgoing",
      "source_weights": {"East": 0.5, "West": 0.5},       // incoming: rolled fresh on every draw
      "destination_weights": {"East": 0.5, "West": 0.5},  // outgoing: rolled fresh on every draw
      "weight": 3,                                   // chance of this requirement being drawn
      "base_processing_days": 2,                     // in random mode these three fields live here
      "delay_chance": 0.1,
      "idle_days": 0
    }
  ]
}
```

Configuration is static. Runtime state (the pattern **position**, the spot state and day counters) lives in the database and is never reset by reloading the configuration. Words are matched regardless of capitals. Optional fields, defaults and limits are in Section 16.1.

### Spot cycle

```
Awaiting car ─────(set-out signalled done)──► Processing (counts down at each day advance; delay rolled daily)
                                              → Ready for pickup  (outgoing: destination fixed here)
Ready for pickup ─(pull signalled done)─────► Idle (idle_days; skipped if 0)
                                              → Awaiting car  (random spots take their next requirement here)
```

- **Incoming spot:** needs a **loaded** car of the right type from the right direction. When pulled, the car is empty.
- **Outgoing spot:** needs an **empty** car of the right type. When pulled, the car is loaded and goes East or West.
- **The spot state is the visible demand signal.** Each spot shows its state in plain language, on the web page now and on LCDs later. Examples (exact wording set during implementation):
  - "Industry #3, spot 2: needs loaded boxcar from East"
  - "Industry #3, spot 2: needs loaded boxcar from East — CSXT 14420 waiting on Locals track"
  - "Industry #1, spot 1: loading TILX 30018"
  - "Industry #1, spot 1: TILX 30018 ready for pickup"

### Spot rules
- **The outgoing destination is fixed when processing completes** (the spot becomes Ready for pickup). For a fixed spot that is `pattern[position]`, with the disruption roll applied then. For a random spot it is the destination rolled at the draw. The car keeps that destination even if its pull is delayed.
- **Pattern position** (fixed spots only) advances by one on **every** completion, with wraparound, even when a disruption flips that one result. Disruptions correct themselves; they don't build up.
- **Delays** are rolled every processing day and can stack without limit. This is intentional. **A delay holds the countdown for one day:** a spot with 2 processing days and one delay hit takes 3 days.
- **The delay chance is capped by the `delay_chance_max` setting** (default 1, meaning no extra cap). The program uses the lower of the spot's `delay_chance` and the cap, so lowering this one setting makes delays rarer everywhere without editing each spot.
- **Idle** is a fixed number of days after a pull before the spot wants another car. It models industries with slow turnover.
- **How days count:**
  - `base_processing_days: 1`: a car set out today is ready for pickup tomorrow.
  - `idle_days: 1`: a car pulled today leaves the spot awaiting a car again tomorrow.
  - `idle_days: 0`: the spot awaits a car again the moment the pull is signalled, so the local can swap cars in the same visit.
- **Random spots** have no pattern memory. Each draw rolls its direction fresh.
- **Rolled a day early:** delay rolls and random-requirement draws (including a random spot's source or destination) are made **one day ahead**. This makes the forecast exact (Section 10). At the layout it looks no different.
  - **A delay roll is made for every spot at every day advance,** whether or not a car turns up. It only counts if the spot is actually Processing at the next day advance. Otherwise it is thrown away and a fresh one is made.
  - Example, the Unloading pit (1 processing day): on Monday evening it is awaiting a car, and the roll for Tuesday evening comes up "delay". Tuesday morning's forecast therefore knows that a hopper set out today won't be ready Wednesday. If the local sets one out, the delay applies that evening, as the forecast expected. If the local skips the set-out, the roll is simply unused.
  - So the rolls always apply to the spot's **actual** state, and a skipped move simply shifts that spot's timeline by a day.
  - **A random spot's next requirement** is drawn a day early, and taken when the spot next becomes Awaiting car.
- **Shortage priority:** when cars are short, the spot that has waited **longest** is served first, with random tie-breaks. A spot that can't be served stays empty and rolls forward.
- **One visit per industry per day:** the local pulls ready cars and spots new cars at an industry in the same visit.
- **Pull before set-out.** If a spot has a car to pull and a car to set out (a swap, typical for a spot with no idle days), the pull must be signalled done before the set-out can be. If the pull doesn't happen, the set-out can't either. The two remain separate signals, so the local can still do one without the other, for example pull a ready car when no replacement is available.
- **A Bad order car freezes its spot.** While a Bad order car (Section 14) sits at a spot, nothing counts down there. When it is pulled:
  - **From a Processing spot,** the spot goes back to **Awaiting car** with its original place in line and the same requirement. The pattern doesn't advance, because the work was never done.
  - **From a Ready for pickup spot,** it counts as a normal pull. The industry had finished with the car before it broke down, so the pattern moves on and idle days apply.

## 6. The Two Worlds (Rest of the Railroad)

East and West are **real physical places**, each standing in for the rest of the railroad in that direction. Both keep their state between sessions, and both are **rebuilt before every session** as a chore (Section 11).

| | East world: return loop | West world: stub staging |
|---|---|---|
| Capacity | One train | 2 car tracks × about 30–35 cars, plus an engine escape track |
| Contents | **Closed set:** exactly the cars that went East on the previous eastbound manifest | **Pool:** every car that has gone West and not yet come back |
| Rebuild | The train is re-sorted using the yard tracks. Its cars must never mix with real yard cars. Nothing is added or removed; every car rides out. The rebuild ends with the train back in the loop, ready for step 1 | The eastbound manifest is built from any cars in staging. The rest stay as spares |
| Planning consequence | Tomorrow's East-supplied cars can only be cars sent East **today** | The software can choose freely from the whole pool |

- Inside a world, loads are Not tracked. A car's load is **assigned when it is chosen for a Local block** (Section 7).
- A world stands in for many places, so variety comes from re-sorting, reassigning loads, and swapping engines.

## 7. Loads

- **Only cars going to or coming from the local have a load status.** Continuing cars and cars in a world are Not tracked.
- **When a car is chosen for a Local block, the target spot sets its load:** loaded for an incoming spot, empty for an outgoing spot.
- **A car that isn't delivered keeps the load it was given.**
- **Return-to-shipper rule:** if a car's next assignment is the **same industry that last loaded it**, it must arrive **empty**, so it can only go to an outgoing spot there. For any other industry it can arrive loaded or empty as needed.
- **Cars pulled from industries keep their real load** while they sit on the Eastbound or Westbound yard tracks. Once they enter a world, the load becomes Not tracked.
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

So each morning the software needs to know which spots will need cars **tomorrow**, of what type and from which direction. All of this comes from the industry configuration and the current spot states: spots already waiting, idle periods ending, ready cars that today's local will pull, cars already assigned (including undelivered cars waiting on Locals), and the day-early rolls. **No forecast-specific configuration is needed.**

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
    16  GATX 7721    tanker   Loaded → Transfer facility   (Local block)
    17  CSXT 14420   boxcar   Empty  → Industry #1         (Local block)
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
INDUSTRY #2
  Pull  NAHX 52210 (covered hopper, bad order) ← Unloading pit  [ done ]
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
  → Westbound track:  NAHX 52210 covered hopper (bad order, leaves the roster at West staging)
                                                       [ B done ]
```

## 13. Signals and Session Flow

### Signals
| Signal | Job | Effect on the records |
|---|---|---|
| West chore done / East chore done | Step 0 | Eastbound manifest built in West staging; westbound manifest built in the East loop; engine moves applied |
| A done | Step 2 | Westbound Local block → Locals track; Westbound track pick-up → westbound manifest; manifest → West staging (step 3 implied); any Bad order car aboard leaves the roster there |
| Pull done (per spot) | Step 4 | Car from spot → local; spot → Idle or Awaiting car (for a Bad order car, see Section 5) |
| Set-out done (per spot) | Step 4 | Car from local → spot; assigned spot cleared; spot → Processing |
| Local back in yard | Step 4 | Local closed; any set-out not signalled = **not delivered**; job B's list produced |
| B done | Step 5 | Returned cars → Eastbound / Westbound / Locals; undelivered cars → Locals (still assigned); job C's list finalized; eastbound manifest at the yard (step 6 implied) |
| C done | Step 7 | Eastbound Local block → Locals track; Eastbound track pick-up → eastbound manifest; manifest → East loop (step 8 implied) |
| Session complete | Day advance | Counters and countdowns advance, day-early rolls made, next session's lists produced |

- **Chores and yard jobs are binary:** done or not done. There is no partial completion. If something physically went differently, the operator fixes the record with the edit tool (Section 14).
- **Only the local has per-move signals:** one per pull and one per set-out.
- **No signal means it didn't happen.** A car not signalled as pulled is still on its spot (the spot stays Ready for pickup, with its destination kept). A car not signalled as set out is still on the local, and job B returns it to the Locals track.
- **Cars for the local are on the local once job A is done.** From that point the local's set-out cars are recorded as being on the local train.
- **Signals are taken in sequence order.** The software always shows the current job. A signal for a later job while an earlier one is still pending is refused with a "waiting on …" message. The two chores can be done in either order, and the local's moves in any order.

### Session complete and pausing
- **A session ends only when the operator signals "session complete."** Powering off, or simply stopping for the day, is a **pause**. On power-up the software resumes at the current job, with every car and spot exactly where the signals left them.
- **"Session complete" is the day advance.** There is no separate correction step before it, because corrections can be made at any time (Section 14).
- **Session complete is accepted only when every chore and yard job (A, B, C) is done.** The trains must clear the main and reach their worlds anyway, and since a session can be paused indefinitely there is never a reason to abandon a yard job. The local is the only job that can leave work undone, and job B cleans up after it.

## 14. Corrections, Persistence and Roster Maintenance

- **Edit tool, available at any time:**
  - **Cars:** set any car's actual location (track, spot, train or world) and load, for example to fix a wrong car spotted or a record found out of step with the layout.
  - **Spots:** set a spot's state directly, for example force it back to Awaiting car. You can also set its days left, its outgoing destination and its pattern position. This lets you correct a car and its spot together, so a car correction never leaves a spot in the wrong state.
  - **Undoing a signal:** the edit tool is also how a wrongly pressed signal is undone. Undo is never done from the physical buttons.
- **Persistence:** every signal and every edit is saved the moment it happens. Turning the system off at any point loses nothing.
- **Cold start**, done once, after a deliberate reset, or when the configuration's industries or spots change (Section 16.1):
  1. **Import the roster from two CSV files.** The car file lists each car's mark, number, type and location, which says whether it is physically in East staging (the loop) or West staging. The engine file lists each engine's mark, number, model, pool and location (Storage, East staging or West staging). The formats are in Section 16.5.
  2. **Both files are checked completely first.** Every problem is listed with its line number, and if there are any, nothing changes. Too many cars for a staging area, or too few engines (Section 4), also stop the cold start. A spot that no car in the roster could ever serve gets a warning.
  3. Everything is cleared and day 1 begins. Every spot starts awaiting a car (random spots draw their first requirement) and every yard track starts empty. The industries fill up over the first few sessions.
  4. The software produces the first session's lists.
- **Roster changes never need a cold start.** They are made on the web page:
  - **Sync roster.** The roster files stay the master list, kept in git. After editing them, "Sync roster" compares them with the records and applies the differences:
    - A car or engine **new** in a file is added. **New cars can only go into West staging.** East staging holds exactly the last eastbound manifest, so a car added there would be stranded.
    - A car or engine **missing** from a file is retired (see below).
    - An existing car keeps its place; the location column only matters for new cars. **A car's type can never change** (different capitals don't count as a change).
    - An existing engine takes the file's pool and model.
    - If any problem is found, nothing changes.
  - Single cars and engines can also be added or retired directly on the web page.
  - **Retiring a car:**
    - **At an industry spot:** the car is marked **Bad order** (it broke down). The next local pulls it ("Pull NAHX 52210 ← Unloading pit (bad order)"), job B sends it to the Westbound track, and it leaves the roster when the westbound manifest reaches West staging. Its spot is frozen until the pull (Section 5).
    - **Anywhere else:** removed at once; take it off the layout. If it was planned into a train, that train runs one car short. If it was assigned to a spot, the spot gets a replacement at the next planning.
  - **Retiring an engine:** removed at once.
- **No backups and no history.** If the state is lost, do a cold start.

## 15. Platform

- **The main program runs on a Raspberry Pi:** Python, with SQLite for the saved state.
- **It serves a web page over Wi-Fi.** Any device with a browser can use it. The first one will be an **old Android tablet**, used purely as a browser. The page should be plain HTML with very little JavaScript, so older Android browsers can handle it. The page shows spot states, the current job, all work lists, the signal buttons and the edit tool.
- **Every signal goes through one input layer.** The core program doesn't know or care where a signal came from. The web page is the first input. Later, ESP32 nodes with push buttons and small LCDs (talking to the Pi over MQTT) plug into the same layer.
- **The long-term goal is for the LCDs and physical buttons to be the main way signals are sent**, with the tablet as a companion for detail and corrections. The hardware design itself (nodes, button layout, what each LCD shows) is still to be done, but it is no longer blocking: it only needs to send the signals in Section 13 and show spot states and the current job.

## 16. Data Model

The model **stores decisions and current positions only. Everything else is worked out when it is needed.** That way a list can never drift out of step with the records: after an edit, every list is simply correct the next time it is shown.

**Plain language everywhere.** Several operators will use the system, so every value a person reads or types uses plain words, never single letters or codes. That applies to the configuration file, the CSV files, the web page, the printed sheets and the database itself. For example: "East staging", not "E"; "Westbound manifest", not "WB"; "Not tracked", not "n/a". Spots and industries are always shown by their `name`, never by their internal id.
- **All plain words are sentence case:** "Awaiting car", "Processing", "Ready for pickup", "Idle", "Loaded", "Empty", "Not tracked", "Local", "Switcher", "Manifest", "Incoming", "Outgoing", "Fixed", "Random".
- **Words typed into a file are matched without regard to capitals or extra spaces,** and are always stored and shown in the spelling above.
- **The one exception:** the session's done flags are stored as 0 or 1. Nobody types them, and the column names say what they mean.

### 16.1 Configuration: a YAML file
The configuration never changes while the system runs. It is a file you edit by hand and keep in git, for example `config.yaml`:

```yaml
settings:
  hold_days_on_locals: 2           # N, Section 8
  eastbound_length_min: 12         # Section 9
  eastbound_length_max: 20
  train_nominal_max: 20            # above this = exception overload train
  three_engines_from: 16           # cars; 15 or fewer = 2 engines
  delay_chance_max: 1              # caps every spot's delay_chance; 1 = no extra cap (Section 5)
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
        requirement_mode: Fixed
        car_type: boxcar
        direction: Outgoing
        pattern: [East, East, West]
        disruption_chance: 0.1
        base_processing_days: 2
        delay_chance: 0.1
        idle_days: 0
      # ... further spots; random-mode spots use possible_requirements (Section 5)
```

- **All settings are changed in this file,** including the Eastbound length range and every capacity. The values shown are the defaults, and any setting left out takes its default.
- **The spot fields are exactly the Section 5 schema.** `position` is runtime state, so it lives in the database; writing it in the file is refused.
- **Optional spot fields:** `disruption_chance`, `delay_chance` and `idle_days` default to 0. A random requirement's `weight` defaults to 1.
- **Limits:**
  - `base_processing_days` is at least 1.
  - `delay_chance` must be below 1, because a chance of 1 would delay the car forever.
  - `eastbound_length_min` can't be larger than `eastbound_length_max`.
  - `eastbound_length_max` can't be larger than East staging's capacity, or a maximum-length eastbound manifest wouldn't fit in the loop.
- **Names:** industry names are unique. Spot names are unique within an industry; two industries may each have a "Loading dock #1".
- **Every problem is reported at once,** in plain language, starting with the industry and spot name. For example: "Northfield Paper, Loading door 2: pattern contains 'Eest' — expected East or West". A misspelled field name gets a "did you mean" hint, and a field written twice in the same section is refused with its line number.
- **Car types are plain text.** A car serves a spot when its type matches the spot's `car_type`, ignoring capitals and spacing: a "Boxcar" car serves a "boxcar" spot.
- **Changing the configuration later:**
  - **These changes need a cold start.** The program refuses to run and lists every difference, for example "Harbor Feed Mill, Unloading pit changed from 'Fixed: covered hopper, Incoming' to 'Fixed: tank car, Incoming'":
    - adding or removing an industry or spot, or changing an `id` or `spot_id`
    - changing a spot's mode, car type or direction
    - changing a random spot's list of possible requirements: adding or removing one, or changing one's car type or direction
  - **Everything else takes effect without one:** names, all settings, processing days, chances, idle days, weights and patterns. If a pattern gets shorter, the spot's position wraps around.
  - To check this, each spot's state records its industry and a short description of it, such as "Fixed: boxcar, Outgoing", at cold start.

### 16.2 State: SQLite, five tables
The program is written in Python, using the standard `sqlite3` module and no ORM. **Each signal and each edit is one complete database transaction.**

| Table | Fields | Notes |
|---|---|---|
| `session` (one row) | day number; done flags: West chore, East chore, job A, local back, job B, job C; local has work today | The current job is worked out from the flags. Flags are stored as 0 or 1 |
| `car` | id, mark, number, type, location (`loc_kind`, `loc_ref`), `seq`, load, last loaded at industry, origin world, assigned spot, destination world, days held on Locals, bad order | Mark + number is unique, ignoring capitals. **Destination world** is set when a loaded car is pulled from an outgoing spot, so job B knows where it goes |
| `engine` | id, mark, number, model (optional), pool (local / switcher / manifest), location, `seq` | |
| `spot_state` | spot id; industry id and identity as at the last cold start; state, days left (processing or idle), pattern position, current random requirement (which one + rolled side), outgoing destination, waiting since day, next delay roll, next random requirement | **Waiting since day** drives oldest-first priority. The **next** fields are the day-early rolls (Section 5). **Identity** (for example "Fixed: boxcar, Outgoing") detects configuration changes that need a cold start |
| `consist_plan` | train (Westbound manifest / Eastbound manifest / Local), seq, car or engine | Written at the day advance. Applied by the matching signal: West chore done, East chore done, or job A done for the Local. Cleared at the next day advance |

- **The database itself refuses impossible values,** such as a car at an unknown place, an unknown load, a code like "E" instead of "East staging", or a second car on a spot. A mistake in the program can therefore never be saved silently.
- **A database made by a different version of the program is refused.** A cold start replaces it.

### 16.3 Locations
Cars and engines use the same location scheme:

| `loc_kind` | `loc_ref` | `seq` means |
|---|---|---|
| World | East staging, West staging | not used |
| Yard | Eastbound track, Westbound track, Locals track | order of arrival (oldest first, for the capacity fallback in Section 9) |
| Spot | the spot (shown by its name) | not used |
| Train | Westbound manifest, Eastbound manifest, Local | position, head to rear; engines lead first |
| Storage | Storage (engines only) | not used |

- **East staging is the hidden return loop.** That is its name in every list and value.
- **Engines are only ever in staging, on a train or in storage,** never on a yard track or at a spot.

- **West staging is a pool.** The software doesn't track which staging track a car is on. Cars are found by number.
- **A train exists only from its chore signal until it arrives.** When it arrives, its cars and engines become part of that world. The local's train exists from A done to B done.

### 16.4 Worked out when needed, never stored
- **Local block:** the cars in a manifest that have an assigned spot.
- **Job A and C pick-ups:** the whole Westbound or Eastbound track at the time of the job. Job C's provisional list is a prediction of that track.
- **Local list:** pulls are the Ready for pickup spots plus any Bad order cars. Set-outs are the cars assigned to spots.
- **Job B:** the routing rules in Section 8, applied to the cars on the local when it is back in the yard.
- **Engine moves on the chore sheets:** the planned consist compared with where the engines are now.
- **Also worked out:** spot display text, the forecast, and the capacity and length checks.

### 16.5 Cold-start CSV files
```
cars.csv      mark,number,type,location        location = East staging or West staging
engines.csv   mark,number,model,pool,location  pool = Local, Switcher or Manifest
                                              location = Storage, East staging or West staging
```
Example rows:
```
cars.csv      CSXT,14420,boxcar,West staging
engines.csv   BNSF,7710,ES44AC,manifest,Storage
```
Every column is required except `model`, which can be left empty if unknown.
- **Column names, locations and pools are matched regardless of capitals.** Columns may come in any order, and blank lines are ignored.
- **Reporting marks are stored in capitals.**
- **Problems are reported with line numbers:** duplicates ("cars.csv, line 67: CSXT 14420 is already on line 2"), unknown locations or pools, missing or unknown columns, empty values, and a file not saved as UTF-8 ("save the file as 'CSV UTF-8'").

## 17. Development Plan

### How we work
- **One step at a time.** Each step comes with automated tests and is committed when they pass.
- **The core logic comes first,** proven from the command line. The web page comes once the engine works, and the Raspberry Pi comes last.
- **Plain language throughout:** values, error messages and labels (Section 16).
- **Tools:**
  - Python 3.13, the version on current Raspberry Pi OS. The PC must never run a newer Python than the Pi.
  - pytest for the automated tests.
  - PyYAML for the configuration file.
  - Flask for the web page.
- **Developed on the Windows PC,** and moved to the Pi at step 12.
- **Design calls the spec doesn't cover** are raised with the user as each step is built, and the confirmed answers go into the next spec version.

### Progress (as of 2026-11-11)
Steps 1–5 are built, tested and pushed to GitHub, with 198 automated tests passing.

| Step | Files | Status |
|---|---|---|
| 1 Project skeleton | `pyproject.toml`, `README.md`, `samples/` (3 made-up industries with 7 spots, 65 cars, 19 engines) | Done |
| 2 Config loading and checking | `trainops/config.py`, `trainops/vocab.py` | Done |
| 3 Database | `trainops/db.py`, `trainops/reconcile.py` (the cold-start check) | Done |
| 4 Cold start and roster | `trainops/rosterfiles.py`, `trainops/coldstart.py`, `trainops/roster.py` | Done |
| 5 Spot logic | `trainops/spots.py` | Done |
| 6 Forecast | | **Next** |

### Milestone 1: The engine (no web page yet)

| Step | What | Done when |
|---|---|---|
| 1 | **Project skeleton:** the `trainops/` package, test setup, and a sample `config.yaml` with 2–3 made-up industries plus sample CSV files, so work can start before the real industry data exists | The tests run; the sample files load |
| 2 | **Config loading and checking:** read the YAML file and check every field. Values are plain words, matched regardless of capitals. Errors are in plain language, for example "Industry #1, Loading door 2: pattern contains 'Eest' — expected East or West" | Good configs load; bad ones give clear messages |
| 3 | **Database:** the five tables (Section 16), a small layer for reading and writing them (one transaction per signal or edit), and the start-up check that refuses a configuration whose industries or spots changed (Section 16.1) | Tables are created; the start-up check is tested |
| 4 | **Cold start and roster:** CSV import with checks (duplicate cars, unknown location, missing column), and reset; roster sync; retiring cars (Bad order at a spot) and engines (Section 14) | The sample roster imports; bad files are rejected clearly |
| 5 | **Spot logic:** processing countdown, daily delays, pattern position and disruption, idle days, random draws, the Bad order freeze, and the rolls made one day ahead (Section 5). Tested thoroughly with a fixed random seed | Every spot rule has a passing test |
| 6 | **Forecast:** tomorrow's demand by direction (Section 10) | Forecast tests pass |
| 7 | **Train planning:** both Local blocks (shortage priority, return-to-shipper, held empties first, shuttle model); the Westbound train from the East staging closed set; the Eastbound train (12–20 draw, minimum, East-staging supply); random order for continuing cars; engine counts and selection; written to `consist_plan` (Sections 8–9) | Planning tests pass |
| 8 | **Signals and the daily sequence:** one entry point for every signal, accepted only in sequence order, with refusals like "waiting on job A"; what each signal changes in the records; local back and job B routing; Bad order pulls and their removal at West staging; session complete running the day advance (Sections 11, 13) | A full day can be signalled through in tests |
| 9 | **Work lists and spot display text:** chore sheets, jobs A, B and C, the local list and spot lines, as plain text (Section 12) | The lists match the Section 12 formats |
| 10 | **Simulator (command line):** plays many days automatically, optionally skipping some local moves at random. Checks invariants after every step: no car lost or duplicated, the East staging set stays closed, capacities are respected, every spot cycles, shortages clear up. Reports train lengths, how often overload trains happen, and how long spots wait | Hundreds of simulated days run with no invariant broken. The simulator is also the tool for tuning the real industry configuration |
| **10a** | **Hand-run test on the virtual layout (command line).** A simple command-line mode shows the current job's list and lets the operator mark each move done. The operator runs sessions by hand in the track-planning software's virtual replica of the layout, following the lists. **Purpose: test the operating rules themselves.** Are the switching moves practical, do train lengths and Local blocks feel right, is the local's work reasonable, is anything in the daily sequence awkward? Rule problems found here are fixed before any web page is built | Several sessions have been run by hand, and any rule changes are agreed and made |

### Milestone 2: The web page

| Step | What | Done when |
|---|---|---|
| 11 | **Web app** (Flask, plain HTML, very little JavaScript). **Main page:** current job, its work list, signal buttons and every spot's state. Also: **printable chore sheets**, the **edit tool** (car location and load; spot state), **roster** (add or retire single cars and engines) and **cold start** (CSV import, reset) | Every function works in a browser |
| **11a** | **Full rehearsal on the virtual layout (web page).** The same exercise as 10a, run the way real sessions will be: signal buttons, spot displays, printed chore sheets, and the edit tool for correcting mistakes. **Purpose: test the interface.** Can you find what you need, are the buttons and wording clear, does correcting a mistake work smoothly? | Several sessions have been run through the web page, and the interface fixes are made |

### Milestone 3: On the layout

| Step | What | Done when |
|---|---|---|
| 12 | **Raspberry Pi deployment:** runs as a service that starts at power-up, reachable over Wi-Fi, tested in the Android tablet's browser | A session runs on the real layout from the tablet |
| 13 | **Later:** an MQTT signal input for the ESP32 button and display nodes, plugged into the same signal entry point (Section 15) | Waits for the hardware design |

## 18. Still Open

- **Industry configuration:** spot counts and settings for Industries #1–3, and whether Industry #4 is built. This is data, not design. The software is driven by configuration, so building can start without it, but it is needed before the first real session.
- **Hardware design** for the LCD and button nodes (Section 15). Not blocking.
- **The Android tablet's version**, to confirm the web page works on its browser. Minor.

## 19. Considered and Rejected

| Idea | Why it was dropped |
|---|---|
| Randomizing the daily train schedule (order and/or number of trains) | The fixed daily sequence works well |
| Weekday vs. weekend (or other repeating) schedule variants | Same |
| Adding extra empties to arrivals to relieve outgoing shortages | Already covered: worlds supply empties for outgoing spots (Section 8) |
| A capacity warning on the Locals track | It holds over 30 cars and the local runs 7–10 |
| JMRI Operations; a spreadsheet | See Section 1 |

## 20. Decision History (superseded ideas, for reference)

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
| (1.41) Python 3.11 | Python 3.13 | Current Raspberry Pi OS ships 3.13 |
| (1.41) "Cooldown" spot state; `cooldown_days` | "Idle"; `idle_days` | A plain, real-world word |
| (1.41) Lowercase plain words (`loaded`, `not tracked`) | Sentence case ("Loaded", "Not tracked") | Reads better on screen |
| (1.41) A reloaded configuration adjusts spot states (new spot added, removed spot ignored) | Industry and spot changes need a cold start; tuning changes don't | Simpler and safer; such changes will be rare |
| (1.41) A car serves a spot only if its type matches exactly | Capitals and spacing are ignored | Plain-language rule |
| (1.41) A new car is added into either world | West staging only | East staging is a closed set |
| (1.41) A retired car is removed anywhere; its spot is fixed by hand | Retired at a spot = Bad order: pulled, sent to West staging, spot frozen until then | Realistic ("car broke down"), and spots stay consistent |
| (1.41) Roster changes one car at a time on the web page | Also "Sync roster" from the roster files | The files stay the master list |

---

## Appendix A — Machine-Readable Spec (AI-facing)

```yaml
spec: digital-train-operations
version: "1.42"
date: 2026-11-11
supersedes: [full-spec_v1.41.md, full-spec_v1.4.md, full-spec_v1.3.md, full-spec_v1.2.md, full-spec_v1.1.md, checkpoint_7-13-26.md, delta_11-06-26.md]
resume_instruction: "Read this appendix only; main body = human prose of same content. Code lives in the repo (trainops/, tests/, samples/); read the module docstrings for detail."
next_version: "user chooses number (e.g. 1.43 small update, 1.5 larger); new file digital-train-operations-full-spec_v<X>.md"
resume_point: "Dev steps 1-5 DONE (198 tests pass, all committed + pushed to main). NEXT: dev step 6 forecast. User took a break after v1.42."
changes_from_1.41: [coding started; steps 1-5 built; Idle replaces cooldown (idle_days); sentence-case words; delay_chance_max setting; spot timing rules; structural config change => cold start; config optional fields/limits/names; roster sync + Bad order retirement; engine minimums; new cars West staging only; car type immutable + matched ignoring capitals; Python 3.13]
changes_from_1.4: [development plan added (main body section 17; appendix dev_plan); design unchanged]
changes_from_1.3: [data model added, cold start via CSV import, roster add/retire via web page, edit tool can set spot state, W staging = pool only, plain-language values everywhere]
changes_from_1.2: [EB length random 12-20 leaving W, pickup blocks never left behind, exception overload train, 20 = nominal not hard cap, local blocks demand-driven, WB non-local cars all continue W]
user_style: "Dictates via speech-to-text; literal 'Period.'/'comma'/'colon' words are punctuation artifacts. Wants design calls the spec doesn't cover raised for confirmation; likes real-world railroad terms (chose 'Idle', 'Bad order')."
plain_language_rule: "HARD RULE (user, 2026-11-09): every value a person reads or types (config YAML, CSV, web page, printed sheets, DB values) uses plain words, never single letters/codes. SENTENCE CASE (2026-11-11): Awaiting car, Processing, Ready for pickup, Idle, Loaded, Empty, Not tracked, Local, Switcher, Manifest, Incoming, Outgoing, Fixed, Random, World, Yard, Spot, Train, Storage; places: East staging, West staging, Eastbound track, Westbound track, Locals track, Westbound manifest, Eastbound manifest, Local, Storage; sides East|West. Typed values matched ignoring capitals + extra spaces. Spots/industries shown by name, never id. Only exception: session done flags stored 0/1. Mid-sentence prose may lowercase (e.g. '6 manifest engines'). Shorthand in THIS appendix is AI-facing only."
status: "design + data model + dev plan complete except industry config data + hardware node design (non-blocking). Build: steps 1-5 done."

build:
  repo: "https://github.com/SerdarSoysal/TrainOps, branch main"
  env: "Windows PC; Python 3.13.7; venv .venv; setup: python -m venv .venv && .venv\\Scripts\\python -m pip install -e \".[dev]\"; tests: .venv\\Scripts\\python -m pytest; git core.autocrlf=true (LF->CRLF warnings harmless)"
  working_rules: [one step at a time, tests per step, commit + push when green, raise uncovered design calls with user, record confirmed decisions in next spec, plain language in values/messages/labels]
  modules:
    vocab.py: "canonical words (constants) + match_word(value, choices) (case/space-insensitive) + same_words(a,b) + either()/both() message joiners"
    config.py: "load_config(path)/parse_config(data) -> Config(settings, industries, spots_by_id); frozen dataclasses Settings, Capacity, Industry, Spot(label='Industry, Spot'), FixedRequirement, RandomRequirement(side_weights={East,West}); ConfigError(problems) lists ALL problems; rejects duplicate YAML keys (line no.), unknown fields (difflib 'did you mean'), position in config"
    db.py: "Database.open(path|':memory:', discard_other_version=False); transaction() context (writes outside refused; no nesting; rollback on error); rows Session, Car(label), Engine(label), SpotState(fresh()), PlanEntry; CHECK constraints enforce plain words + location rules; unique index one car per spot; SCHEMA_VERSION=1 (user_version); clear_all(); remove_from_consist_plans(); set_consist_plan(train, engine_ids, car_ids)"
    reconcile.py: "spot_identity(spot) e.g. 'Fixed: boxcar, Outgoing' / 'Random: boxcar, Incoming; tank car, Outgoing'; create_spot_states (cold start only); check_config(db, config) -> notes, raises ColdStartNeeded(reasons) (also when no cold start yet); applies pattern wrap"
    rosterfiles.py: "read_cars/read_engines(path) -> (rows, problems) with line numbers; CarRow/EngineRow(key=(MARK, number)); engine_count_problems (MIN_ENGINES switcher 1, local 2, manifest 6); RosterFileError(problems)"
    coldstart.py: "cold_start(db, config, cars_path, engines_path, rng=None) -> notes; checks both files + staging capacity + engine minimums first; then clear_all, import, create_spot_states, roll_ahead each spot; warns for spots no roster car can serve"
    roster.py: "retire_car (at spot -> bad_order=True; else removed + removed from plans), retire_engine, sync_roster(db, config, cars, engines) -> notes (raises RosterFileError, changes nothing on any problem), where_is(config, kind, ref)"
    spots.py: "pure functions on (Spot config, SpotState): need(), upcoming_need() -> Need(car_type, direction, side, base_processing_days, delay_chance, idle_days); set_out(); pull(day, bad_order); advance(rng, settings, new_day, frozen); roll_ahead(); SpotRuleError"
  samples: "samples/config.yaml: Northfield Paper (Loading door 1 boxcar Outgoing [East,East,West]; Loading door 2 boxcar Outgoing [West,East] idle 1; Chemical unloading tank car Incoming East), Harbor Feed Mill (Unloading pit covered hopper Incoming West idle 1; Bagged feed dock boxcar Outgoing [East]), Transfer Facility (Team track 1 flatcar Incoming East; Team track 2 Random: boxcar Incoming E/W, covered hopper Outgoing, tank car Incoming East). cars.csv 65 cars (16 East staging, 49 West staging; gondolas + autoracks = through-only). engines.csv 19 (14 manifest [3 in East staging], 4 local [1 with empty model], 1 switcher)."
  todo_later_steps:
    - "step 6+: car type matching uses vocab.same_words"
    - "step 7: local list includes Bad order pulls; retired car assigned to a spot -> spot gets replacement at next planning"
    - "step 8: day advance calls spots.advance(frozen=<bad-order car at spot>) for every spot; Bad order pull -> spots.pull(bad_order=True); job B routes Bad order car -> Westbound track; A_done: Bad order cars arriving West staging removed from roster"
    - "step 10: CLI must print UTF-8 (em dash shows as '?' in Windows console)"
    - "step 11: web page: Sync roster button, single add/retire, cold start (Database.open(discard_other_version=True))"

dev_plan:
  working_rules: [one step at a time, tests per step, commit when green, plain language in values/messages/labels]
  stack: {python: "3.13 (matches current Pi OS; PC never newer than Pi)", tests: pytest, config: PyYAML, web: Flask (plain HTML, minimal JS), db: stdlib sqlite3 no ORM}
  dev_machine: Windows PC; move to Pi at step 12
  milestone_1_engine:
    1: "DONE project skeleton"
    2: "DONE config load + validation"
    3: "DONE database (5 tables, repository layer, 1 txn per signal/edit, cold-start check on structural config change)"
    4: "DONE cold start (CSV import + validation, reset) + roster sync + retire (Bad order)"
    5: "DONE spot logic (countdown, delays + cap, pattern/disruption, idle, random draws, day-ahead rolls, bad-order freeze; seeded-RNG tests)"
    6: "NEXT forecast"
    7: train planning (local blocks, WB from East staging closed set, EB 12-20 draw/floor/E-supply, continuing order, engines, consist_plan)
    8: signals + daily sequence (single entry point, ordering/refusals, effects, local_back + job B routing, Bad order handling, session complete = day advance)
    9: work lists + spot display text (plain text, section-12 formats)
    10: simulator CLI (auto-run many days, optional random skipped local moves, invariant checks, stats; also tool for tuning real industry config)
    10a: HAND-RUN on virtual layout via CLI manual mode; purpose = test OPERATING RULES; fix rules before web work
  milestone_2_web:
    11: "Flask web app (main page = current job, list, signal buttons, spot states; printable chore sheets; edit tool cars+spots; roster sync/add/retire; cold start import/reset)"
    11a: FULL REHEARSAL on virtual layout via web page; purpose = test INTERFACE
  milestone_3_layout:
    12: Pi deployment (service at power-up, Wi-Fi, tablet browser test)
    13: "later: MQTT input for ESP32 nodes via same signal entry point"

philosophy:
  scope: digitize ops paperwork; no train-movement automation
  car_tracking: individual (roster)
  build: "custom (JMRI rejected: no demand planning, spot mechanics, industry jobs, button fit; spreadsheet rejected)"
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
  car_fields: [mark (stored CAPITALS), number, type (IMMUTABLE), location, load(Loaded|Empty|Not tracked), last_loaded_at_industry, origin_world(East staging|West staging), assigned_spot(nullable), days_held_on_locals, dest_world(nullable; set on pull of loaded car from outgoing spot), bad_order(0/1)]
  location_values: see data_model.locations
  any_car_type_can_serve_industry: true  # role from config; unused types = through-only
  car_type_matching: "ignores capitals + spacing (vocab.same_words)"
  engine_groups:
    local_pool: {per_train: 2, pick: random}
    switcher: {count: 1, dedicated: true}
    manifest_pool: {size: ~14, per_train: "2 if len<=15 else 3 (overload always 3)", len_basis: "max(arriving, departing)", eligible: "engines at that world + storage", pick: random}
  engine_minimums: {switcher: 1, local: 2, manifest: 6}  # enforced at cold start + sync; guarantees no shortage
  engine_shortage: not modeled (ample)

spots:
  capacity: 1 car
  schema: "all: spot_id (internal), name (shown), requirement_mode Fixed|Random; Fixed: car_type, direction Incoming|Outgoing, source (Incoming) | pattern + disruption_chance (Outgoing), base_processing_days, delay_chance, idle_days; Random: possible_requirements[car_type, direction, source_weights (Incoming) | destination_weights (Outgoing), weight, base_processing_days, delay_chance, idle_days]; side values East|West"
  states: [Awaiting car, Processing, Ready for pickup, Idle]
  transitions:
    Awaiting->Processing: "on setout_done; days_left = base_processing_days; waiting_since_day KEPT (bad-order restore)"
    Processing->Ready: "at day advance when countdown reaches 0; outgoing dest fixed here (Fixed: pattern[position] + disruption flip roll; Random: drawn side); Fixed Outgoing position += 1 (wrap) on EVERY completion"
    Ready->Idle_or_Awaiting: "on pull_done; idle_days > 0 -> Idle(days_left=idle_days); idle_days == 0 -> Awaiting car immediately (same-visit swap), waiting_since = that day"
    Idle->Awaiting: "at day advance when idle countdown reaches 0; waiting_since = new day"
    random_spot_entering_Awaiting: takes pre-drawn next requirement (next_* cleared, redrawn at next advance)
  timing:
    delay: "next_delay True at a day advance while Processing -> countdown held 1 day; stacks uncapped"
    delay_chance_effective: "min(requirement delay_chance, settings.delay_chance_max)"
    examples: "base 1: set out today -> Ready tomorrow; idle 1: pulled today -> Awaiting tomorrow; idle 0: Awaiting at pull"
    preroll: "at EVERY day advance (after transitions), for EVERY spot: Random draws next requirement (weight, then side weights) if none; next_delay rolled with chance of the requirement the spot will process next (upcoming_need: Ready/Idle random -> next draw). Roll used only if spot is Processing at next advance, else discarded (CONFIRMED). Cold start: random spot draws first requirement + all rolls."
    disruption: rolled at completion (not prerolled)
  bad_order_spot:  # CONFIRMED 2026-11-11
    freeze: "spot with Bad order car: advance(frozen=True) -> no countdowns"
    pull_from_Processing: "-> Awaiting car, original waiting_since (place in line), same requirement, no pattern advance"
    pull_from_Ready: "normal pull (work done; position already advanced; idle applies)"
  display: plain-language state per spot = visible demand signal (web now, LCD later); e.g. "needs loaded boxcar from East [— CSXT 14420 waiting on Locals]"
  incoming: needs loaded car of type from source dir; pulled -> empty
  outgoing: needs empty; pulled -> loaded, dest already fixed at Ready
  random_mode: no position; fresh E/W roll per draw
  shortage: oldest-waiting first (waiting_since_day), random tiebreak; unserved stays Awaiting, rolls forward
  local_visit: one per industry per day, pull+spot combined
  pull_before_setout: setout on an occupied spot only after its pull_done; separate signals (pull alone OK if no replacement car)
  config_vs_state: config static; runtime state persists, never reset on reload

worlds:
  rebuilt: before every session (chore)
  loads_inside: Not tracked
  E: closed set = exactly cars of prior EB manifest; re-sorted via yard tracks, never mixed with yard cars; nothing added/removed; all ride out; rebuild ends with train back in loop for step 1 (CONFIRMED)
  W: pool; EB built from any staging cars; rest stay as spares; WB arrival couples onto spares OK

loads:
  tracked_only_for: local-bound/local-originated cars; continuing + world cars = Not tracked
  assign_at: Local-block selection; incoming spot -> Loaded; outgoing spot -> Empty
  undelivered: keeps assigned load
  return_to_shipper: if target industry == last_loaded_at -> must be Empty (outgoing spot only)
  pulled_cars: keep real load on Eastbound/Westbound tracks; -> Not tracked on entering world

supply_to_spots:
  incoming: loaded car from spot's source world (fixed source | rolled source)
  outgoing_empty:
    1: held empty of type on Locals track first, any origin (CONFIRMED)
    2: "else from world == scheduled destination (shuttle): dest W -> empty from W staging (EB local block); dest E -> empty from E loop (WB local block)"
    scheduled_dest: "fixed: pattern[position] (pre-disruption); random: dest rolled at draw"
    disruption: rolled at completion; may ship to other side than supplied from; accepted
  undelivered_car: back to Locals via job B, keeps assigned_spot, first in line next run; forecast counts spot as covered

routing_pulled_cars:
  loaded_from_outgoing: Eastbound|Westbound track per dest fixed at Ready
  empty_from_incoming:
    if_type_used_by_any_outgoing_spot: hold on Locals up to N days (default 2, configurable; counted per day advance), then -> track toward origin_world
    else: immediately -> track toward origin_world
  bad_order: -> Westbound track always; removed from roster when WB arrives West staging

train_building:
  local_blocks_demand_driven:  # CONFIRMED 2026-11-09; computed at day advance from forecast, net of held empties + undelivered cars on Locals
    WB_block: serves TODAY's E-supplied demand (set out step 2, spotted same day)
    EB_block: serves TOMORROW's W-supplied demand (set out step 7, spotted next day)
  local_block: rear; filled from ANY matching-type car available in that world (prior role irrelevant)
  continuing: random order ahead of local block
  WB_continuing: all WB cars not in local block continue to W staging (job A cuts local block only)  # CONFIRMED
  WB_length: fixed = E closed set (yesterday's EB arrival in E)
  EB_length:
    draw: random int [eastbound_length_min, eastbound_length_max], config defaults 12, 20; counted LEAVING W staging (before yard work)
    floor: local_block + tomorrow's E-supply cars not covered by Eastbound pickup; draw raised to floor
    cap: W staging cars available (shortage rules if below floor)
    continuing_pick: random from W pool; unchosen stay as spares
    W_capacity: hard check retained
  E_supply: EB (+ its Eastbound pickup) must carry cars for TOMORROW's E-supplied demand (E-sourced incoming loads + empties for outgoing spots scheduled to ship E not covered by held empties)
  post_yard_length: "arriving - setout + pickup; ENTIRE pickup track always taken (jobs A and C); >20 -> exception overload train (expected rare, 1-2 cars)"
  overload_propagates: EB overload -> next day's WB same size (E closed set); WB may exceed 20 after job A too; same rule
  overflow_safeguard: only if E loop (~30) or W staging capacity would be exceeded -> oldest pickups first, rest wait; not expected
  leftover_engines: both worlds -> storage at chore
  retired_planned_car: train runs one car short (removed from consist_plan)

forecast:
  E_supplied_for_day_D: chosen from cars sent E on day D-1 EB; set out D step2 before local -> same-day spot
  W_supplied: EB set out at step7 after local -> spotted next day
  direction: incoming = source; outgoing (no held empty) = scheduled destination
  inputs: industry config + spot state + assigned/undelivered cars + prerolls (spots.upcoming_need, next_delay); no extra config
  assumes: today's local completes all listed moves; deviations self-correct next forecast
  shortages: accepted; self-correct ~next day

daily_sequence:  # strictly sequential, no overlap
  0: "pre-session chores (rebuild WB in E loop via yard tracks; rebuild EB in W staging; engine moves)  [signals: chore_W_done, chore_E_done; either order]"
  1: WB leaves E loop -> yard (holds on main)  [implied]
  2: "switcher job A: cut rear Local block -> Locals; pick up Westbound track -> rear  [A_done]"
  3: WB -> W staging  [implied by A_done; Bad order cars aboard leave roster]
  4: local job; leaves returned cars on main  [pull_done(spot), setout_done(spot), local_back]; auto-skipped if no local work
  5: "switcher job B: sort returned cars -> Eastbound|Westbound|Locals; undelivered -> Locals  [B_done]"
  6: EB leaves W staging -> yard (only after 5 done)  [implied by B_done]
  7: "switcher job C: cut rear Local block -> Locals; pick up Eastbound track -> rear  [C_done]"
  8: EB -> E loop, overnight  [implied by C_done]
  end: session_complete == day advance
  facts: WB pickup = yesterday's pulls; EB pickup = today's pulls; E loop empty at 1, filled at 8

signals:
  input_layer: single entry point for all signals; sources = web page now, ESP32/MQTT later; core agnostic
  chore_and_yard_jobs: binary done/not-done, no partial
  local: per-move pull_done / setout_done (per spot) + manual local_back by local operator
  no_signal: didn't happen (unpulled car stays on spot, Ready, keeps dest; unset-out car stays on local -> job B returns it to Locals)
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
  chore_sheet_per_world: {sections: ["1 engines storage->staging", "2 engines staging->storage", "3 train list: engines lead-first; cars head->rear; local-block cars show load+dest"], empty_section: "prints 'none'"}
  switcher_A_C: ["cut rear N cars (listed) -> Locals", "pick up <dir> track (listed, entire track) -> rear", "note if >20: exception overload train"]
  local: "per industry, per move with done button: 'Pull <car> <- <spot>' / 'Spot <car> -> <spot>'; Bad order pull marked '(bad order)'; specific cars; train order irrelevant; setout unlocks after pull on same spot"
  switcher_B: "per car -> Eastbound|Westbound|Locals (with reason: loaded dest / empty to origin / held / not delivered, retry next run / bad order, leaves roster at West staging)"

corrections_persistence:
  edit_tool: anytime; set car location + load; set spot state (state, days_left, out_dest, position); also undoes mistaken signals; never via physical buttons
  persist: every signal + edit saved immediately (SQLite), one transaction each
  cold_start:
    when: once, on deliberate reset, or when config industries/spots change structurally (see data_model.config.changes)
    checks: "both CSVs fully checked first (line-numbered problems); staging capacity; engine minimums; any problem -> nothing changes; warning per spot no roster car can serve"
    effect: "clear all; day 1; cars in listed world (origin = that world, load Not tracked); engines Storage|world; every spot Awaiting car (random draws first requirement) + day-early rolls; yard empty; generate first session lists (step 7+)"
    other_version_db: replaced (Database.open(discard_other_version=True))
  roster_changes:  # CONFIRMED 2026-11-11; NEVER need a cold start; via web page
    sync_roster: "re-read cars.csv + engines.csv (files = master list in git): new car -> added, WEST STAGING ONLY (E = closed set); new engine -> added at listed location; missing car/engine -> retired; existing car keeps place (file location ignored); car TYPE CAN NEVER CHANGE (capitals not a change) -> refused; existing engine takes file pool + model; capacity + engine minimums checked; any problem -> nothing changes"
    single_add_retire: also available on web page
    retire_car_at_spot: "marked Bad order: next local pulls it '(bad order)', job B -> Westbound track, leaves roster when WB reaches West staging; spot frozen until pull"
    retire_car_elsewhere: "removed at once (take off layout); removed from consist_plan (train runs one short); if assigned to a spot, spot gets replacement at next planning"
    retire_engine: removed at once (+ from consist_plan)

data_model:
  principle: store decisions + current positions only; derive everything else on demand (lists never drift)
  impl: Python, stdlib sqlite3, no ORM
  config:  # YAML file (e.g. config.yaml), hand-edited, in git, static at runtime
    settings: {hold_days_on_locals: 2, eastbound_length_min: 12, eastbound_length_max: 20, train_nominal_max: 20, three_engines_from: 16, delay_chance_max: 1, capacity: {east_staging: 30, west_staging: 70, yard_track: 35}}  # each optional -> default
    industries: "[{id, name, spots: [section-5 spot schema; spot_id internal, name shown]}]"
    optional_defaults: {disruption_chance: 0, delay_chance: 0, idle_days: 0, weight: 1}
    limits: ["base_processing_days >= 1", "delay_chance < 1", "chances 0..1", "eastbound_length_min <= eastbound_length_max <= capacity.east_staging", "weights >= 0 with at least one > 0", "weight > 0"]
    names: industry names unique; spot names unique WITHIN an industry; spot_id unique across file
    errors: "ConfigError lists ALL problems: '<Industry>, <Spot>: <problem>'; unknown field -> 'did you mean'; duplicate YAML key -> line number; position in config refused"
    changes:  # CONFIRMED 2026-11-11
      need_cold_start: [industry/spot added or removed, id or spot_id changed, spot mode/car type/direction changed, random possible_requirements list changed (added/removed, car type or direction)]
      no_cold_start: [names, settings, processing days, chances, idle days, weights, patterns (shorter pattern -> position wraps)]
      mechanism: "spot_state stores industry_id + identity at cold start; check_config at start-up compares (identity compared ignoring capitals) and refuses with all reasons"
    car_types: free text; match ignoring capitals/spacing
  tables:
    session: "single row: day, west_chore_done, east_chore_done, job_a_done, local_back, job_b_done, job_c_done, local_has_work (flags 0/1); current job derived from flags"
    car: "id, mark, number (unique mark NOCASE + number), type, loc_kind, loc_ref, seq, load, last_loaded_industry, origin_world, assigned_spot, dest_world, days_held, bad_order"
    engine: "id, mark, number, model(opt), pool(Local|Switcher|Manifest), loc_kind, loc_ref, seq"
    spot_state: "spot_id, industry_id, identity, state, days_left, position, requirement_number (1-based), requirement_side, out_dest, waiting_since_day, next_delay, next_requirement_number, next_requirement_side"
    consist_plan: "train(Westbound manifest|Eastbound manifest|Local), seq, car_id|engine_id (exactly one; FK); written at day advance; applied by west_chore/east_chore/job_a done; cleared next day advance"
    integrity: "CHECK constraints enforce plain words + per-kind location rules; unique index = one car per spot; schema version via PRAGMA user_version"
  locations:  # shared by car + engine; values are plain language
    World: {ref: [East staging, West staging], seq: unused, note: "East staging = hidden return loop"}
    Yard: {ref: [Eastbound track, Westbound track, Locals track], seq: arrival order (oldest first), cars_only: true}
    Spot: {ref: spot_id (displayed by spot name), seq: unused, cars_only: true}
    Train: {ref: [Westbound manifest, Eastbound manifest, Local], seq: "head->rear; engines lead first"}
    Storage: {ref: Storage, engines_only: true}
    W_staging: pool only; no per-track tracking  # CONFIRMED
    train_lifetime: "manifest: chore signal -> arrival (dissolves into world); LOCAL: A_done -> B_done"
  derived_not_stored: [local block = manifest cars with assigned_spot, job A/C pickup = whole track at job time (C provisional = prediction), local list = Ready spots + Bad order cars + assigned cars, job B routing (section 8 rules), chore-sheet engine moves = plan vs current location, spot display text, forecast, capacity/length checks]
  csv:
    cars: "mark,number,type,location  (location East staging|West staging)"
    engines: "mark,number,model,pool,location  (pool Local|Switcher|Manifest; location Storage|East staging|West staging)"
    required: all columns except engine model (may be empty)
    parsing: "column names/locations/pools ignore capitals; any column order; blank lines skipped; marks stored CAPITALS; UTF-8 (BOM ok); problems with line numbers (duplicate, unknown location/pool, missing/unknown/doubled column, empty values, wrong value count, not UTF-8)"
    example: ["CSXT,14420,boxcar,West staging", "BNSF,7710,ES44AC,Manifest,Storage"]
  backups: none (loss -> cold start)

platform:
  brain: Python on Raspberry Pi
  db: SQLite
  ui: web page served over Wi-Fi; any browser; first client = old Android tablet (browser only); plain HTML, minimal JS
  ui_contents: spot states, current job, work lists, signal buttons, edit tool, roster sync/add/retire, cold start
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

confirmed_2026-11-08:
  - strict signal ordering (later job refused while earlier pending)
  - local's set-out cars count as on the local from A_done
  - job C pickup list finalized at B_done
  - outgoing dest uses pre-disruption pattern entry for empty sourcing; disruption still rolled at completion

confirmed_2026-11-09:
  - local blocks demand-driven (WB = today's E demand, EB = tomorrow's W demand)
  - all non-local WB cars continue to W staging
  - EB length random 12-20 leaving W staging, floor = local block + uncovered E-supply cars
  - pickup blocks never left behind; >20 = exception overload train; applies to WB too
  - data model (YAML config + 5 SQLite tables + derive-on-demand); W staging pool only; cold start via CSV; edit tool sets spot state; capacities + EB min/max are settings; engines.csv location required; engine model optional; plain-language rule; spot name field; case-insensitive matching

confirmed_2026-11-11:
  - Python 3.13
  - config optional fields default (chances/idle 0, weight 1, settings to defaults); delay_chance < 1; base_processing_days >= 1; eastbound_length_max <= east_staging capacity
  - delay_chance_max setting = global cap, effective = min(spot, cap), default 1
  - industry names unique; spot names unique within industry only
  - car type matching ignores capitals; car type immutable
  - sentence case for all plain words; Cooldown -> Idle, cooldown_days -> idle_days
  - session flags 0/1 OK
  - engines only in staging/train/storage
  - structural config change -> cold start; tuning changes don't (split as in data_model.config.changes)
  - roster changes never need cold start; Sync roster; new cars West staging only; engine minimums 1/2/6; marks stored in capitals
  - Bad order: retire at spot -> pulled, -> Westbound track, leaves roster at West staging; spot frozen until pull; Processing pull -> Awaiting car keeping place in line, no pattern advance; Ready pull -> normal pull
  - retired car elsewhere/engine -> removed at once; planned train runs short
  - spot timing: delay holds countdown 1 day (stacking); base 1 -> Ready next day; idle 1 -> Awaiting next day; idle 0 -> Awaiting at pull
  - delay preroll made for every spot each advance; used only if Processing at next advance

derived_not_explicitly_confirmed: none
```
