# Digital Train Operations — Full Design Specification

**Version 1.44 — 2026-11-13**

This document is the complete design for the Digital Train Operations project as of this version. It replaces version 1.43 (`digital-train-operations-full-spec_v1.43.md`) and all earlier working files, which are kept only for history. Where they disagree with this document, this document wins.

The main body is written to be read by a person. **Appendix A** is a compact, machine-readable version of the same design for use by an AI assistant when resuming work.

**What changed since 1.43:** step 10a, the hand-run test, is done. Its three findings are built and tested:
- **The manifests' own moves have jobs and signals.** There are four new jobs: **Westbound to yard**, **Westbound to West staging**, **Eastbound to yard** and **Eastbound to East staging**. Each ends with its own signal, such as "Westbound in yard". Once both chores are done, **jobs run in parallel:** each signal waits only for the jobs it really needs (Sections 11 and 13).
- **The local's list names its engines:** "Pick up engines X and Y from storage." (Section 12.3).
- **There are two chore modes, Full and Quick.** A quick chore reuses the train that arrived in that staging the day before and changes only its rear, which saves most of the rebuilding. The mode is set in the configuration and can be changed on the main page; a change takes effect at the next day advance (Sections 9 and 12.1).
- **The database format is now 3,** so a database from version 1.43 needs a cold start (Section 16.2).

Version 1.43 had folded in steps 6–10. See Section 20 for the full history.

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
- **Destination world**, for a loaded car pulled from an outgoing spot. It carries the destination fixed when the spot became Ready for pickup (Section 5) so the Local return job can route the car.
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
- **The spot state is the visible demand signal.** Each spot shows one plain-language line, on the web page now and on LCDs later. For example:
  - "Harbor Feed Mill, Unloading pit: Awaiting car — needs a loaded covered hopper from the West"
  - "Harbor Feed Mill, Unloading pit: Awaiting car — needs a loaded covered hopper from the West — NAHX 52210 waiting on the Locals track"
  - "Northfield Paper, Loading door 2: Awaiting car — needs an empty boxcar to load for the East"
  - "Northfield Paper, Chemical unloading: Processing TILX 211089 (tank car) — 2 days left"
  - "Northfield Paper, Loading door 1: Ready for pickup: ABOX 50762 (boxcar), loaded for the West"
  - "Harbor Feed Mill, Unloading pit: Idle — 1 day before it wants a car again"
  - The days left can turn out a day longer if a delay hits.

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
- **Pull before set-out.** If a spot has a car to pull and a car to set out (a swap, typical for a spot with no idle days), the pull must be signalled done before the set-out can be. If the pull doesn't happen, the set-out can't either. The two remain separate signals, so the local can still do one without the other, for example pull a ready car when no replacement is available. **This is the only order the local's moves have to follow** (Section 13).
- **A Bad order car freezes its spot.** While a Bad order car (Section 14) sits at a spot, nothing counts down there. When it is pulled:
  - **From a Processing spot,** the spot goes back to **Awaiting car** with its original place in line and the same requirement. The pattern doesn't advance, because the work was never done.
  - **From a Ready for pickup spot,** it counts as a normal pull. The industry had finished with the car before it broke down, so the pattern moves on and idle days apply.

## 6. The Two Worlds (Rest of the Railroad)

East and West are **real physical places**, each standing in for the rest of the railroad in that direction. Both keep their state between sessions, and both are **rebuilt before every session** as a chore (Section 11).

| | East world: return loop | West world: stub staging |
|---|---|---|
| Capacity | One train | 2 car tracks × about 30–35 cars, plus an engine escape track |
| Contents | **Closed set:** exactly the cars that went East on the previous eastbound manifest | **Pool:** every car that has gone West and not yet come back |
| Rebuild | The train is re-sorted using the yard tracks. Its cars must never mix with real yard cars. Nothing is added or removed; every car rides out. The rebuild ends with the train back in the loop, ready for step 1. A quick chore only moves the Local block to the rear (Section 9) | The eastbound manifest is built from any cars in staging. The rest stay as spares. A quick chore reuses yesterday's westbound instead (Section 9) |
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
- **When several cars would do, one is chosen at random.** Among held empties, the one held longest is used first.
- **Undelivered cars keep their assignment.** A car the local doesn't deliver goes back to the Locals track (the Local return job), still assigned to its spot, and is first in line on the next run. The forecast treats that spot as covered, so no second car is sent for it.

### Routing cars pulled from industries
- **Loaded cars from outgoing spots** go to the **Eastbound** or **Westbound** yard track, according to the destination fixed when processing completed.
- **Empty cars from incoming spots:**
  1. If **any outgoing spot on the layout can use that car type** (a fixed outgoing spot of that type, or a random spot with an outgoing requirement for it), the empty waits on the **Locals** track for reuse. It waits **up to N days** (default **2**, configurable), counted at each day advance.
  2. If no spot could use it (for example empty propane tankers with no propane loader), it goes straight to the yard track for the **world it came from**.
  3. If it is still unused after N days, it goes back to the world it came from. **The Local return job** takes it off the Locals track to the yard track toward that world, and the next manifest that way carries it (2026-11-11). Days are counted at each day advance: an empty pulled on Monday can be used by the local on the N days after (Tuesday and Wednesday when N is 2), and goes home at Thursday's Local return job.
- **A car no longer wanted.** A car waiting on the Locals track for a spot that no longer wants it is released: its type and load no longer match what the spot needs now or next, usually after an edit-tool change. An empty that some outgoing spot could use becomes an ordinary held empty. Anything else goes home the same way as an expired empty (2026-11-11).

## 9. Building Trains

### The Local blocks are driven by demand
Both Local blocks are decided at the day advance from the forecast (Section 10). Each one contains the cars the spots need, minus anything already covered by held empties or undelivered cars on the Locals track. The two blocks serve different days:
- **Westbound Local block** (cut at Switch westbound, step 2): serves **today's** East-supplied demand. Those cars are spotted by the same day's local.
- **Eastbound Local block** (cut at Switch eastbound, step 7): serves **tomorrow's** West-supplied demand. It is set out after today's local has run, so its cars are spotted the next day.

### Car selection and order
- **The Local block always goes at the rear.** It is the block the switcher cuts off at this town.
- **The Local block is filled from any car of a matching type that is available in that world.** A car that was a continuing car yesterday can be today's Local car. Loads are assigned as in Section 7, at the moment the car is chosen.
- **The order of cars inside the Local block is never planned.** The block is at the rear; the crews arrange the cars within it as suits them.
- **The rest of the train (continuing cars) is in random order** in a full chore. A quick chore keeps yesterday's order (see Chore modes below).
- **Every westbound car that is not in the Local block continues to West staging.** Switch westbound cuts only the Local block. The rest of the train, plus the Westbound pick-up block added at the rear, runs on to the West.

### Westbound manifest (from the East loop)
- **Its cars are fixed:** exactly the cars the previous eastbound manifest took into the East loop, re-sorted so the Local block is at the rear. Its length is therefore whatever yesterday's eastbound train delivered to the East.

### Eastbound manifest (from West staging)
- **Length drawn at random:** each day the eastbound manifest leaves West staging with a random length between **12 and 20 cars**. Both numbers are configuration values with defaults of 12 and 20. The length counts the train as it **leaves West staging**, before any yard work.
- **Raised to the minimum it must carry:** the train is never shorter than its Local block plus the cars needed for **tomorrow's East-supplied demand** that its Eastbound pick-up block won't already cover. If the draw is lower than that, it is raised to the minimum.
- **Lowered to what staging holds:** if West staging has fewer suitable cars than the draw, the train runs shorter. If it can't even meet the demand, the normal shortage rules apply (Section 10).
- **Continuing cars are picked at random** from the West staging pool in a full chore. The cars not chosen stay behind as spares.
- **East-side supply:** the eastbound manifest, including the pick-up block it adds at the yard, must carry suitable cars for **tomorrow's** East-supplied demand. That means loaded cars for East-sourced incoming spots and empties for outgoing spots scheduled to ship East. The East is a closed set, so those cars must be on this train.
- **West staging capacity** is still checked as a hard limit.

### Chore modes: Full and Quick (2026-11-13)
Rebuilding both manifests from scratch every day is the biggest chore. A **quick chore** reuses the train that arrived in that staging the day before and changes only its rear. A **full chore** is the rebuild described above.

- **East loop (the westbound manifest):** the cars stay in the order the eastbound arrived in. Only the Local block cars are moved to the rear. Nothing is added or removed; the East loop is a closed set anyway.
- **West staging (the eastbound manifest):** yesterday's westbound is reused the other way round, so its rear car becomes the eastbound's head car. Then:
  - **Length:** yesterday's length is kept, but brought within the 12–20 range (`eastbound_length_min` to `eastbound_length_max`). It is then raised to the train's minimum and lowered to what staging holds, as in a full chore.
  - **Cars come off at the rear.** The rearmost cars the train doesn't need go to the spare tracks. Cars needed for tomorrow's East-supplied spots stay wherever they are in the train.
  - **Cars go on at the rear.** First any East-supply cars from the spare tracks, then spare cars to make up the length, and the Local block last.
  - **Cars already in the train are used first.** When a car in yesterday's train fits a Local block or East-supply need, it is chosen, so a car never comes off only for a car like it to go on. The Local block takes the rearmost car that fits, because it ends at the rear anyway. East supply takes the frontmost, because it can ride anywhere and that leaves the rear cars for the Local block. Only when no car in the train fits is a spare chosen, at random. A Local block car from the middle of the train is moved to the rear.
- **Engines follow the regular rules** in both modes (Power, below).
- **One mode for both worlds.** The `chore_mode` setting (Full or Quick, Section 16.1) is the mode after a cold start. A toggle on the main page changes it. **A change takes effect at the next day advance:** today's chores were planned at the last one and stay as planned.
- **The first day after a cold start always gets full chores,** because no train order is known in staging yet. The planning notes say so.
- Quick chores keep yesterday's length instead of drawing a new one, so they make more overload trains (Section 18).

### Length after yard work: the exception overload train
- **Pick-up blocks are never left behind.** Each switcher job adds the **whole** pick-up track to its manifest: the Westbound track at Switch westbound, the Eastbound track at Switch eastbound.
- After yard work, a manifest's length is: arriving cars − Local set-out + pick-up block. **If that comes to more than 20 cars, the train runs as an exception overload train.** This is expected to be rare and only by 1–2 cars.
- **An overload carries into the next day.** The East loop is a closed set whose cars all ride out, so a 22-car eastbound arrival becomes a 22-car westbound manifest the next morning. After Switch westbound, that westbound train can be over 20 as well, and the same rule applies.
- **The hard limits are the destinations:** the East loop holds about 30 cars, and West staging must have room. If one of these were ever exceeded, the oldest pick-up cars would go first and the rest would wait a day. That is a safeguard only and isn't expected to happen. West staging's room is counted with the eastbound manifest still in it, since the westbound normally arrives first. (Trimming the eastbound's randomly chosen cars instead was considered and rejected, 2026-11-11.)

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
- **A spot needs a car on a day** if, during that day's local, it is Awaiting car already; or Ready for pickup with no idle days (pulled and refilled in the same visit, waiting from that day); or Processing with a Bad order car (the pull frees it, keeping its place in line).
- **One case can't be foreseen:** a random spot refilled today that will be ready again tomorrow with no idle days (1 processing day). Its next requirement isn't drawn until tomorrow's day advance, so no car can be sent in time, and it waits about a day like any shortage. This is accepted (2026-11-11). Drawing two requirements ahead, or forbidding that combination, was rejected.
- **Sample results** from the simulator: with the sample industries, spots wait well under a day on average, and shortages are rare and clear up by the next day.

## 11. Daily Sequence

Each manifest's moves on the main line are jobs with their own signals (2026-11-13). **Once both chores are done, several jobs can be under way at once:** each signal waits only for the jobs it really needs. The table lists the jobs in their usual order.

| Step | Job | Who | Can start when | Signal |
|---|---|---|---|---|
| 0 | **Pre-session chores:** rebuild the westbound manifest in the East loop (re-sorted using the yard tracks) and the eastbound manifest in West staging, and make the engine moves | Operator, from the chore sheets | — | West chore done; East chore done (either order) |
| 1 | **Westbound to yard:** the westbound manifest leaves the East loop and holds on the main in the yard | Road crew | Both chores are done | Westbound in yard |
| 2 | **Switch westbound:** move the Local block into the Locals track; move the Westbound track's cars onto the train | Yard switcher | Westbound in yard | Switch westbound done |
| 3 | **Westbound to West staging** | Road crew | Switch westbound is done. Runs alongside steps 4–8 | Westbound in West staging |
| 4 | **Local job:** pull and spot at each industry; on return, leave the returned cars on the main | Local crew | Switch westbound is done | Pull done and Set-out done for each spot; **Local back in yard** |
| 5 | **Local return job:** move the local's returned cars to the Eastbound, Westbound or Locals track (undelivered cars back to Locals), and move held empties that are going home off the Locals track | Yard switcher | Local back in yard | Local return job done |
| 6 | **Eastbound to yard:** the eastbound manifest leaves West staging and comes to the main in the yard | Road crew | Both chores are done, so it runs alongside steps 1–5. It may leave at once and wait in a passing siding, but **it can't enter the yard until the Local return job is done** | Eastbound in yard |
| 7 | **Switch eastbound:** move the Local block into the Locals track; move the Eastbound track's cars onto the train | Yard switcher | Eastbound in yard | Switch eastbound done |
| 8 | **Eastbound to East staging:** the eastbound manifest runs into the East loop and sits there overnight | Road crew | Switch eastbound is done | Eastbound in East staging |
| — | **Session complete = day advance** | Operator | Every job is done | Session complete |

Results of this order:
- **Both chores come first.** Neither manifest leaves its staging until both chores are done (2026-11-13).
- **A train joins its staging only at its arrival signal.** For example, a Bad order car aboard the westbound leaves the roster at "Westbound in West staging".
- **The main page shows every job that is open at the moment.**
- Cars set out from the westbound manifest can be spotted **the same day**. That includes refilling spots the local empties today, because those spots are known in advance.
- Cars set out from the eastbound manifest are spotted **the next day**.
- The westbound pick-up holds **yesterday's** local pulls. The eastbound pick-up holds **today's**.
- The East loop empties at step 1 and fills at step 8, so it never needs room for two trains.
- **If the local has no work on a given day,** the software skips the local job and its "Local back in yard" signal automatically.
- **If the Local return job has nothing to do** (the local brought nothing back and no held empty is going home), it is skipped automatically too (2026-11-11).

## 12. Session Work Lists

Each job has a list, shown on the web page (Section 15); the chore sheets can also be printed. The page shows the lists of every open job. **Every list is worked out from the records when it is shown,** so it always matches the signals sent so far. The chore sheets, Switch westbound's list and the local's list are ready at the day advance. **The Local return job's list appears when the local signals it is back in the yard,** and **Switch eastbound's pick-up is final only once the Local return job is done**, because both depend on what the local actually did.

**The lists say what moves where, never in what order.** The crews decide the order that suits them (2026-11-11).

### 12.1 Pre-session chore sheet (one per world)
A full chore's sheet has three sections, always in this order. A section with nothing to do says **"none"**. Once the chore is signalled, the sheet shows "✓ done".

```
WEST STAGING — Eastbound manifest
1. Engines from storage → staging:  BNSF 6180, UP 7022
2. Engines from staging → storage:  none
3. Train list
   Engines (lead first):  BNSF 6180, UP 7022
   Cars (head → rear):
     1  CSXT 14587   boxcar
     2  NAHX 52210   covered hopper
     ...
    11  NS 473355    boxcar          Empty → Northfield Paper   (Local block)
    12  ADMX 44983   covered hopper  Loaded → Harbor Feed Mill   (Local block)
                                        [ West chore done ]

EAST LOOP — Westbound manifest
   ...
                                        [ East chore done ]
```

Load and destination industry appear only on Local-block cars.

**A quick chore's sheet** (Section 9) says so in its title and lists the car moves between the engine moves and the train list. In West staging there are three of them; in the East loop only the move to the rear:

```
WEST STAGING — Eastbound manifest  (Quick chore)
1. Engines from storage → staging:  BNSF 6180
2. Engines from staging → storage:  UP 7022
3. Cars off the train → spare tracks:  BNSF 534410 gondola
4. Cars from the spare tracks → train:  NS 473355 boxcar
5. Cars moved to the rear of the train (Local block):  ADMX 44983 covered hopper
6. Train list
   ...

EAST LOOP — Westbound manifest  (Quick chore)
1. Engines from storage → staging:  none
2. Engines from staging → storage:  CSXT 3021
3. Cars moved to the rear of the train (Local block):  TILX 211089 tank car
4. Train list
   ...
```

### 12.2 Yard jobs: Switch westbound, Local return job, Switch eastbound
Each yard job is **a single list of moves, grouped by where the cars are and where they go.** "The main" is where the manifest, or the local back from its run, is standing.

```
WESTBOUND MANIFEST — Switch westbound
  Move 3 cars from the main to the Locals track:
      ABOX 50231 boxcar, CSXT 601233 flatcar, BNSF 727455 boxcar
  Move 2 cars from the Westbound track to the main:
      NS 472816 boxcar, UP 41230 covered hopper
  (Train leaves with 22 cars — exception overload train)
                                        [ Switch westbound done ]

LOCAL RETURN JOB — the local's cars on the main
  Move 2 cars from the main to the Locals track:
      NAHX 52210 covered hopper, TBOX 665893 boxcar
  Move 1 car from the main to the Eastbound track:
      PROX 33102 tank car
  Move 2 cars from the main to the Westbound track:
      ABOX 50762 boxcar, UP 260411 flatcar (bad order)
  Move 1 car from the Locals track to the Westbound track:
      ADMX 44983 covered hopper
                                        [ Local return job done ]

EASTBOUND MANIFEST — Switch eastbound
  Move 1 car from the Eastbound track to the main:
      PROX 33102 tank car
  (More cars may reach the Eastbound track during the Local return job.)
                                        [ Switch eastbound done ]
```

- The overload note appears only when the train will leave with more than 20 cars (Section 9). If a destination is full (the safeguard in Section 9), the list says how many cars stay on the pick-up track.
- The Local return job's moves follow Section 8: loaded cars to the track for their destination; unloaded empties held on Locals or sent home; undelivered cars back to Locals, still assigned; Bad order cars to the Westbound track; held empties going home off the Locals track.
- There is no reason per car. A Bad order car is marked "(bad order)" so the crew can tell which one it is.
- The line under Switch eastbound shows only until the Local return job is done.

### 12.3 Local job (by industry)
The local takes **specific** cars from the Locals track. The order of cars in the local train doesn't matter, and its moves can be done in any order, at any industry.

```
LOCAL — day 5
  Pick up engines NS 5302 and BNSF 2310 from storage.
NORTHFIELD PAPER
  Pull  ABOX 50762 (boxcar, loaded)   ← Loading door 1  [ Pull done ]
  Spot  TBOX 665893 (boxcar, empty)   → Loading door 1  [ Set-out done ]  (after pull)
  Spot  BNSF 727455 (boxcar, empty)   → Loading door 2  ✓ done
HARBOR FEED MILL
  Pull  NAHX 52210 (covered hopper, bad order)  ← Unloading pit  [ Pull done ]
PULLED, BACK TO THE YARD
  UP 363120 boxcar  → Westbound track
                                        [ Local back in yard ]
```

- **The only ordering rule:** where a spot has both a pull and a set-out, its set-out waits for that spot's pull ("(after pull)").
- **A finished set-out** stays on the list, marked done.
- **A finished pull** leaves its industry: the car is listed under "Pulled, back to the yard" with only the track it goes to next. Once a car leaves an industry, only where it goes next matters; the spot it came from is not recorded (2026-11-11).
- **Buttons are offered only when they can be accepted:** a set-out button appears once its spot is empty.
- **The first line names the local's engines** (2026-11-13). There is no move back to storage on the list, because the local ends every day in storage.

### 12.4 Main-line jobs: the manifests' moves
Each of the four main-line jobs (Section 11) has a short list: where the train goes, with its engines and cars.

```
WESTBOUND MANIFEST — Westbound to yard
  From East staging to the main in the yard (3 engines, 16 cars)
                                        [ Westbound in yard ]

WESTBOUND MANIFEST — Westbound to West staging
  From the yard to West staging (3 engines, 17 cars)
  Bad order, take off the layout in West staging: NAHX 52210.
                                        [ Westbound in West staging ]

EASTBOUND MANIFEST — Eastbound to yard
  From West staging to the main in the yard (2 engines, 14 cars)
  May leave West staging now, but waits in a passing siding until the Local return job is done.

EASTBOUND MANIFEST — Eastbound to East staging
  From the yard to East staging (3 engines, 18 cars)
                                        [ Eastbound in East staging ]
```

- The Bad order line appears only when the westbound carries a Bad order car.
- The eastbound's "waits in a passing siding" line takes the place of its button until the Local return job is done.

## 13. Signals and Session Flow

### Signals
| Signal | Job | Effect on the records |
|---|---|---|
| West chore done / East chore done | Step 0 | The manifest is made up in its world from the plan. Engines planned from Storage join it; other engines left in that world go to Storage. A planned car or engine that isn't where the plan expects (for example after an edit) is left out, with a note |
| Westbound in yard | Step 1 | Nothing moves in the records; Switch westbound can start |
| Switch westbound done | Step 2 | Westbound Local block → Locals track; Westbound track → westbound manifest. The local is made up from its planned engines and cars, or skipped if it has no work. Whether it has work is checked again at this point, so a car marked Bad order after planning is still pulled |
| Westbound in West staging | Step 3 | The manifest joins West staging, its cars keeping their place in the train for a quick chore tomorrow. Any Bad order car aboard leaves the roster |
| Pull done (per spot) | Step 4 | Car from spot → local. A car from an outgoing spot becomes Loaded for the destination fixed at Ready for pickup; a car from an incoming spot becomes Empty. Spot → Idle or Awaiting car (for a Bad order car, see Section 5) |
| Set-out done (per spot) | Step 4 | Car from local → spot; assigned spot cleared; spot → Processing |
| Local back in yard | Step 4 | Local closed; any set-out not signalled = **not delivered**; the Local return job's list is produced, or the job is skipped if it has nothing to do |
| Local return job done | Step 5 | Returned cars → Eastbound / Westbound / Locals; undelivered cars → Locals (still assigned); held empties going home → the track toward their world; the local's engines → Storage. Switch eastbound's pick-up is now final; the eastbound manifest may now enter the yard |
| Eastbound in yard | Step 6 | Nothing moves in the records; Switch eastbound can start. Refused until the Local return job is done: "The eastbound can't enter the yard until the Local return job is done." |
| Switch eastbound done | Step 7 | Eastbound Local block → Locals track; Eastbound track → eastbound manifest |
| Eastbound in East staging | Step 8 | The manifest joins the East loop, its cars keeping their place in the train |
| Session complete | Day advance | Held empties count a day; every spot advances (frozen while it holds a Bad order car) and gets its day-early rolls; the next day is planned, in the chore mode the page's toggle is set to, and its lists produced |

- **Chores, main-line jobs and yard jobs are binary:** done or not done. There is no partial completion. If something physically went differently, the operator fixes the record with the edit tool (Section 14).
- **Only the local has per-move signals:** one per pull and one per set-out.
- **No signal means it didn't happen.** A car not signalled as pulled is still on its spot (the spot stays Ready for pickup, with its destination kept). A car not signalled as set out is still on the local, and the Local return job returns it to the Locals track.
- **Cars for the local are on the local once Switch westbound is done.** From that point the local's set-out cars are recorded as being on the local train.
- **Each signal waits only for the jobs it needs** (Section 11; 2026-11-13). The software shows every open job. A signal whose jobs aren't done yet is refused with a "Waiting on …" message naming the jobs that can be worked now, for example "Waiting on Switch westbound." The two chores can be done in either order.
- **The local's moves are accepted in any order,** across industries and within one. The only refusal is a set-out at a spot that still holds a car: "Pull ABOX 50762 from Northfield Paper, Loading door 1 first." (2026-11-11)
- **A refused signal changes nothing.**
- **Signal names** are matched regardless of capitals and extra spaces: "West chore done", "East chore done", "Westbound in yard", "Switch westbound done", "Westbound in West staging", "Pull done", "Set-out done", "Local back in yard", "Local return job done", "Eastbound in yard", "Switch eastbound done", "Eastbound in East staging", "Session complete".
- **The chore mode toggle is not a signal.** It can be changed at any time and only affects the next day advance (Section 9).

### Session complete and pausing
- **A session ends only when the operator signals "Session complete."** Powering off, or simply stopping for the day, is a **pause**. On power-up the software resumes at the open jobs, with every car and spot exactly where the signals left them.
- **"Session complete" is the day advance.** There is no separate correction step before it, because corrections can be made at any time (Section 14).
- **Session complete is accepted only when every job is done:** both chores, the four main-line jobs, Switch westbound, the Local return job and Switch eastbound (a skipped job counts as done). The trains must clear the main and reach their worlds anyway, and since a session can be paused indefinitely there is never a reason to abandon a yard job. The local is the only job that can leave work undone, and the Local return job cleans up after it.

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
    - **At an industry spot:** the car is marked **Bad order** (it broke down). The next local pulls it ("Pull NAHX 52210 ← Unloading pit (bad order)"), the Local return job sends it to the Westbound track, and it leaves the roster when the westbound manifest reaches West staging. Its spot is frozen until the pull (Section 5).
    - **Anywhere else:** removed at once; take it off the layout. If it was planned into a train, that train runs one car short. If it was assigned to a spot, the spot gets a replacement at the next planning.
  - **Retiring an engine:** removed at once.
- **No backups and no history.** If the state is lost, do a cold start.

## 15. Platform

- **The main program runs on a Raspberry Pi:** Python, with SQLite for the saved state.
- **It serves a web page over Wi-Fi.** Any device with a browser can use it. The first one will be an **old Android tablet**, used purely as a browser. The page should be plain HTML with very little JavaScript, so older Android browsers can handle it. The page shows spot states, the open jobs, all work lists, the signal buttons, the chore mode toggle (Section 9) and the edit tool.
- **Every signal goes through one input layer.** The core program doesn't know or care where a signal came from. The web page is the first input. Later, ESP32 nodes with push buttons and small LCDs (talking to the Pi over MQTT) plug into the same layer.
- **The long-term goal is for the LCDs and physical buttons to be the main way signals are sent**, with the tablet as a companion for detail and corrections. The hardware design itself (nodes, button layout, what each LCD shows) is still to be done, but it is no longer blocking: it only needs to send the signals in Section 13 and show spot states and the open jobs.

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
  chore_mode: Full                 # Full or Quick (Section 9); the mode after a cold start
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

- **All settings are changed in this file,** including the Eastbound length range and every capacity. `chore_mode` is only the starting mode: after a cold start the main page's toggle sets it. The values shown are the defaults, and any setting left out takes its default.
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
| `session` (one row) | day number; done flags: West chore, East chore, Westbound in yard, Switch westbound, Westbound in West staging, local back, Local return job, Eastbound in yard, Switch eastbound, Eastbound in East staging; local has work today; chore modes: the toggle's (for the next day advance), and today's for West staging and for the East loop | The open jobs are worked out from the flags. Flags are stored as 0 or 1; chore modes as Full or Quick |
| `car` | id, mark, number, type, location (`loc_kind`, `loc_ref`), `seq`, load, last loaded at industry, origin world, assigned spot, destination world, days held on Locals, bad order | Mark + number is unique, ignoring capitals. **Destination world** is set when a loaded car is pulled from an outgoing spot, so the Local return job knows where it goes |
| `engine` | id, mark, number, model (optional), pool (local / switcher / manifest), location, `seq` | |
| `spot_state` | spot id; industry id and identity as at the last cold start; state, days left (processing or idle), pattern position, current random requirement (which one + rolled side), outgoing destination, waiting since day, next delay roll, next random requirement | **Waiting since day** drives oldest-first priority. The **next** fields are the day-early rolls (Section 5). **Identity** (for example "Fixed: boxcar, Outgoing") detects configuration changes that need a cold start |
| `consist_plan` | train (Westbound manifest / Eastbound manifest / Local), seq, car or engine | Written at the day advance. Applied by the matching signal: West chore done, East chore done, or Switch westbound done for the Local. Cleared at the next day advance |

- **The database itself refuses impossible values,** such as a car at an unknown place, an unknown load, a code like "E" instead of "East staging", or a second car on a spot. A mistake in the program can therefore never be saved silently.
- **A database made by a different version of the program is refused.** A cold start replaces it. The current database format is 3 (new session columns for the main-line jobs and the chore modes; cars in a world keep their place in the train).

### 16.3 Locations
Cars and engines use the same location scheme:

| `loc_kind` | `loc_ref` | `seq` means |
|---|---|---|
| World | East staging, West staging | cars: their place in the train that last arrived there (1 = behind the engines), kept for a quick chore; spare cars have none. Engines: not used |
| Yard | Eastbound track, Westbound track, Locals track | order of arrival (oldest first, for the capacity fallback in Section 9) |
| Spot | the spot (shown by its name) | not used |
| Train | Westbound manifest, Eastbound manifest, Local | position, head to rear; engines lead first |
| Storage | Storage (engines only) | not used |

- **East staging is the hidden return loop.** That is its name in every list and value.
- **Engines are only ever in staging, on a train or in storage,** never on a yard track or at a spot.

- **West staging is a pool.** The software doesn't track which staging track a car is on. Cars are found by number.
- **A train exists only from its chore signal until its arrival signal** (Westbound in West staging, Eastbound in East staging). Then its cars and engines become part of that world. The local's train exists from Switch westbound done to Local return job done.

### 16.4 Worked out when needed, never stored
- **Local block:** the cars in a manifest that have an assigned spot.
- **Switch westbound's and Switch eastbound's pick-ups:** the whole Westbound or Eastbound track at the time of the job (the overflow safeguard aside). Before the Local return job is done, Switch eastbound's list shows the track so far.
- **Local list:** pulls are the Ready for pickup spots plus any Bad order cars. Set-outs are the local's planned cars.
- **Local return job:** the routing rules in Section 8, applied to the cars on the local when it is back in the yard, plus held empties going home from the Locals track.
- **Engine moves on the chore sheets:** the planned consist compared with where the engines are now.
- **A quick chore's car moves:** yesterday's train compared with the planned one.
- **The open jobs:** from the session's done flags.
- **Also worked out:** spot display text, the forecast, the buttons that can be pressed now, and the capacity and length checks.

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

### Progress (as of 2026-11-13)
Steps 1–10a are done. Step 10a's three findings are built, with 365 automated tests passing, and pushed to GitHub. **Next is step 11, the web page.**

| Step | Files | Status |
|---|---|---|
| 1 Project skeleton | `pyproject.toml`, `README.md`, `samples/` (3 made-up industries with 7 spots, 65 cars, 19 engines) | Done |
| 2 Config loading and checking | `trainops/config.py`, `trainops/vocab.py` | Done |
| 3 Database | `trainops/db.py`, `trainops/reconcile.py` (the cold-start check) | Done |
| 4 Cold start and roster | `trainops/rosterfiles.py`, `trainops/coldstart.py`, `trainops/roster.py` | Done |
| 5 Spot logic | `trainops/spots.py` | Done |
| 6 Forecast | `trainops/forecast.py` | Done |
| 7 Train planning | `trainops/planning.py` (cold start now plans day 1) | Done |
| 8 Signals and the daily sequence | `trainops/signals.py`, `trainops/yardwork.py` (the yard jobs, worked out from the records) | Done |
| 9 Work lists and spot display text | `trainops/worklists.py` | Done |
| 10 Simulator and hand-run command line | `trainops/simulate.py`, `trainops/cli.py` | Done |
| 10a Hand-run test on the virtual layout | (the user, with `play`); findings: main-line signals and parallel jobs, the local's engines, Full and Quick chores | Done (2026-11-13) |
| 11 Web page | | **Next** |

**The command line** (run from the project folder; the `samples/` files are used unless `--config`, `--cars` and `--engines` are given):
```
.venv\Scripts\python -m trainops simulate --days 365
.venv\Scripts\python -m trainops simulate --days 200 --seed 7 --skip-chance 0.2 --bad-order-chance 0.1
.venv\Scripts\python -m trainops simulate --days 365 --chore-mode quick     (full, quick or mixed)
.venv\Scripts\python -m trainops play --cold-start     (first time, or to start over)
.venv\Scripts\python -m trainops play                  (carry on where you stopped)
```
- **`simulate`** plays many days on its own. After every signal it checks that no car is lost or duplicated, that the East loop stays a closed set, that staging capacities hold, that each spot and its car agree, and that cars in the worlds and on the Locals track are where they should be. With quick chores it also checks that reused cars keep yesterday's order, that the Local block is at the rear, and that the westbound gains no cars. It sends the main-line signals too, "Westbound in West staging" at a random point in the day. It reports train lengths, overload trains, 3-engine days, how many quick chores were done, cars set out and pulled per day, how often held empties are reused, each spot's average and longest wait and days short, and the most cars on each yard track at once. `--chore-mode` is full, quick, or mixed (changed at random each day); the default is the configuration's `chore_mode`. A simulated year takes about 40 seconds.
  - The simulator never adds cars, so a long run with a high bad-order chance slowly runs down the roster and shortages grow. Real retirements are expected to be extremely rare, so this only matters for the simulator.
- **`play`** shows the lists of every open job with numbered buttons; typing a number sends that signal (`s` = spot states, `l` = every list, `c` = change the chore mode, `q` = quit). Under the day's heading it shows the chore modes, for example "Chores: full today; quick from the next day advance (c = change)". The state is saved after every signal in `trainops.db`. **A `trainops.db` from version 1.43 needs `play --cold-start`** (database format 3).

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
| 8 | **Signals and the daily sequence:** one entry point for every signal, each accepted once the jobs it needs are done, with refusals like "Waiting on Switch westbound."; what each signal changes in the records; local back and the Local return job's routing; Bad order pulls and their removal at West staging; session complete running the day advance (Sections 11, 13) | A full day can be signalled through in tests |
| 9 | **Work lists and spot display text:** chore sheets, Switch westbound, the Local return job, Switch eastbound, the local list and spot lines, as plain text (Section 12) | The lists match the Section 12 formats |
| 10 | **Simulator (command line):** plays many days automatically, optionally skipping some local moves and retiring cars as Bad order at random. Checks invariants after every step: no car lost or duplicated, the East staging set stays closed, capacities are respected, every spot cycles, shortages clear up. Reports train lengths, how often overload trains happen, and how long spots wait | Hundreds of simulated days run with no invariant broken. The simulator is also the tool for tuning the real industry configuration |
| **10a** | **Hand-run test on the virtual layout (command line).** The command line's `play` mode shows the open jobs' lists and lets the operator mark each move done. The operator runs sessions by hand in the track-planning software's virtual replica of the layout, following the lists. **Purpose: test the operating rules themselves.** Are the switching moves practical, do train lengths and Local blocks feel right, is the local's work reasonable, is anything in the daily sequence awkward? Rule problems found here are fixed before any web page is built | Several sessions have been run by hand, and any rule changes are agreed and made |

### Milestone 2: The web page

| Step | What | Done when |
|---|---|---|
| 11 | **Web app** (Flask, plain HTML, very little JavaScript). **Main page:** the open jobs, their work lists, signal buttons, the chore mode toggle and every spot's state. Also: **printable chore sheets**, the **edit tool** (car location and load; spot state), **roster** (add or retire single cars and engines) and **cold start** (CSV import, reset) | Every function works in a browser |
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
- **The eastbound length range** (`eastbound_length_max`, Section 16.1). With the sample industries the simulator shows overload trains on about 10% of days at the default maximum of 20 (longest 26 cars), about 1% at 18 and none at 16, with no extra shortages. **Quick chores make about twice as many:** they keep yesterday's length instead of drawing a new one. Over 365 days and three seeds, each manifest ran overloaded on 21–42 days with full chores and on 49–77 days with quick ones; the longest trains were about the same (23–26 cars). The design expects overloads to be rare, so this should be set from simulator runs, in the chore mode mostly used, once the real industry configuration exists.

## 19. Considered and Rejected

| Idea | Why it was dropped |
|---|---|
| Randomizing the daily train schedule (order and/or number of trains) | The fixed daily sequence works well |
| Weekday vs. weekend (or other repeating) schedule variants | Same |
| Adding extra empties to arrivals to relieve outgoing shortages | Already covered: worlds supply empties for outgoing spots (Section 8) |
| A capacity warning on the Locals track | It holds over 30 cars and the local runs 7–10 |
| JMRI Operations; a spreadsheet | See Section 1 |
| Drawing a random spot's requirement two days ahead, or forbidding a 1-day, no-idle random requirement | The one-day wait it prevents is rare (Section 10) |
| Making room in a full East loop by dropping the eastbound's randomly chosen cars | The spec's safeguard stays: oldest pick-ups first, the rest wait a day (Section 9) |
| Planning the order of cars in a Local block or on the local (for example grouped by industry) | Choosing the switching order is the crew's job (Section 12) |
| Recording which spot a pulled car came from | Once a car leaves an industry, only where it goes next matters (Section 12) |
| Letting each manifest leave after its own chore | Both chores come first (Section 11; 2026-11-13) |
| A quick chore that reuses yesterday's engines in reverse order (for example UP 44, BNSF 55, BNSF 77 becoming BNSF 77, BNSF 55, UP 44 by way of the engine escape), or a third chore mode for it | Engines follow the regular rules in both modes; two modes are enough (2026-11-13) |

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
| (1.1) The list for sorting the local's returned cars known before the session | Produced when the local is back in the yard; includes undelivered cars | It depends on what the local actually did |
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
| (1.42) Switcher jobs A, B and C; signals "A done", "B done", "C done" | Switch westbound, the Local return job, Switch eastbound; "… done" signals | Plain names |
| (1.42) The eastbound manifest leaves West staging only after job B | It may leave earlier and wait in a passing siding; it can't enter the yard until the Local return job is done | The yard is the real constraint |
| (1.42) Job B always run | The Local return job is skipped when it has nothing to do | Nothing to sort |
| (1.42) Yard lists as numbered steps ("cut the rear N cars", "pick up … add to rear"); job B with a reason per car | One list of moves per yard job, grouped from → to, with no order and no reasons | The crew chooses the order |
| (1.43) The manifests' moves on the main line implied, with no signals | Four main-line jobs, each with a signal ("Westbound in yard" and so on) | Step 10a: the operator confirms each train's moves |
| (1.43) Signals taken strictly in sequence; one current job | Each signal waits only for the jobs it needs; the page shows every open job | Step 10a: the westbound's run to West staging and the eastbound's run to the yard overlap other jobs |
| (1.43) Bad order cars leave the roster at Switch westbound | At "Westbound in West staging" | A train joins its staging only at its arrival signal |
| (1.43) The local's list didn't name its engines | "Pick up engines X and Y from storage." | Step 10a; the same as the manifests |
| (1.43) Every chore rebuilds the whole train | Full or Quick chores, with a toggle on the main page | Step 10a: saves most of the daily rebuilding |
| (1.43) Cars in a world have no order | They keep their place in the train that last arrived | Needed for quick chores |

---

## Appendix A — Machine-Readable Spec (AI-facing)

```yaml
spec: digital-train-operations
version: "1.44"
date: 2026-11-13
supersedes: [full-spec_v1.43.md, full-spec_v1.42.md, full-spec_v1.41.md, full-spec_v1.4.md, full-spec_v1.3.md, full-spec_v1.2.md, full-spec_v1.1.md, checkpoint_7-13-26.md, delta_11-06-26.md]
resume_instruction: "Read this appendix only; main body = human prose of same content. Code lives in the repo (trainops/, tests/, samples/); read the module docstrings for detail."
next_version: "user chooses number (e.g. 1.44 small update, 1.5 larger); new file digital-train-operations-full-spec_v<X>.md"
resume_point: "Dev steps 1-10a DONE (365 tests pass, all committed + pushed to main). Step 10a (user hand-run) findings built 2026-11-13: main-line jobs/signals + parallel jobs, local engines line, Full/Quick chore modes. NEXT: step 11 (Flask web app), incl. the chore mode toggle and open-jobs view."
changes_from_1.43: [step 10a done; 4 main-line jobs + signals (Westbound to yard/'Westbound in yard', Westbound to West staging/'Westbound in West staging', Eastbound to yard/'Eastbound in yard', Eastbound to East staging/'Eastbound in East staging'); jobs run in parallel after both chores (each signal waits only for what it needs; open_jobs replaces current_job); train joins staging at its arrival signal (Bad order leaves roster at Westbound in West staging); local list names its engines; chore modes Full/Quick (config chore_mode + page toggle effective next day advance); world cars keep seq = place in last arriving train; DB format 3]
changes_from_1.42: [steps 6-10 built (forecast, planning, signals, work lists, simulator + play CLI); switcher jobs renamed (A->Switch westbound, B->Local return job, C->Switch eastbound; DB format 2); lists give moves never order (yard jobs grouped from->to; pulled car shown only by next track); Local return job auto-skipped when empty; eastbound may leave West staging before Local return job, can't enter yard until it's done; local moves any order (only set-out-after-own-pull); expired held empties + released stray cars go home via Local return job; East loop overflow stays as spec; random not-drawn forecast case accepted; simulator finding on eastbound_length_max]
changes_from_1.41: [coding started; steps 1-5 built; Idle replaces cooldown (idle_days); sentence-case words; delay_chance_max setting; spot timing rules; structural config change => cold start; config optional fields/limits/names; roster sync + Bad order retirement; engine minimums; new cars West staging only; car type immutable + matched ignoring capitals; Python 3.13]
changes_from_1.4: [development plan added (main body section 17; appendix dev_plan); design unchanged]
changes_from_1.3: [data model added, cold start via CSV import, roster add/retire via web page, edit tool can set spot state, W staging = pool only, plain-language values everywhere]
changes_from_1.2: [EB length random 12-20 leaving W, pickup blocks never left behind, exception overload train, 20 = nominal not hard cap, local blocks demand-driven, WB non-local cars all continue W]
user_style: "Dictates via speech-to-text; literal 'Period.'/'comma'/'colon' words are punctuation artifacts. Wants design calls the spec doesn't cover raised for confirmation; likes real-world railroad terms (chose 'Idle', 'Bad order', job names). NEVER call the switcher jobs A/B/C, even in conversation."
plain_language_rule: "HARD RULE (user, 2026-11-09): every value a person reads or types (config YAML, CSV, web page, printed sheets, DB values) uses plain words, never single letters/codes. SENTENCE CASE (2026-11-11): Awaiting car, Processing, Ready for pickup, Idle, Loaded, Empty, Not tracked, Local, Switcher, Manifest, Incoming, Outgoing, Fixed, Random, World, Yard, Spot, Train, Storage; places: East staging, West staging, Eastbound track, Westbound track, Locals track, Westbound manifest, Eastbound manifest, Local, Storage; sides East|West; jobs: Pre-session chores, Switch westbound, Local, Local return job, Switch eastbound, Session complete. Typed values matched ignoring capitals + extra spaces. Spots/industries shown by name, never id. Only exception: session done flags stored 0/1. Mid-sentence prose may lowercase (e.g. '6 manifest engines'). Shorthand in THIS appendix is AI-facing only."
moves_not_order_rule: "HARD RULE (user, 2026-11-11): software lists WHAT moves WHERE, never the order. No ordering/grouping of cars inside a Local block or on the local; yard jobs = one list grouped by from->to; a pulled car is described only by where it goes next (pulled-from spot never stored/shown)."
status: "design + data model + dev plan complete except industry config data + hardware node design (non-blocking). Build: steps 1-10a done; step 11 next."

build:
  repo: "https://github.com/SerdarSoysal/TrainOps, branch main"
  env: "Windows PC; Python 3.13.7; venv .venv; setup: python -m venv .venv && .venv\\Scripts\\python -m pip install -e \".[dev]\"; tests: .venv\\Scripts\\python -m pytest (365 tests, ~3 min); git core.autocrlf=true (LF->CRLF warnings harmless). Write files with encoding utf-8 (Windows default cp1252 breaks on em dash/arrows). Git Bash heredocs break on apostrophes: write a script file instead."
  cli: "python -m trainops simulate [--days 365 --seed 1 --skip-chance 0 --bad-order-chance 0 --chore-mode full|quick|mixed (default: config chore_mode) --config/--cars/--engines (default samples/)]; python -m trainops play [--db trainops.db] [--cold-start] (shows every open job; c toggles chore mode; a v1.43 trainops.db needs --cold-start). Output reconfigured to UTF-8."
  working_rules: [one step at a time, tests per step, commit + push when green, raise uncovered design calls with user, record confirmed decisions in next spec, plain language in values/messages/labels, moves never order]
  modules:
    vocab.py: "canonical words (constants) + match_word(value, choices) + same_words(a,b) + either()/both(); SIGNALS (13 names, sequence order) + SPOT_SIGNALS; job names JOB_CHORES, WESTBOUND_TO_YARD, SWITCH_WESTBOUND, WESTBOUND_TO_WEST_STAGING, JOB_LOCAL, LOCAL_RETURN, EASTBOUND_TO_YARD, SWITCH_EASTBOUND, EASTBOUND_TO_EAST_STAGING, JOB_END; CHORE_FULL/CHORE_QUICK/CHORE_MODES"
    config.py: "load_config(path)/parse_config(data) -> Config(settings, industries, spots_by_id); frozen dataclasses Settings (incl. chore_mode Full|Quick, default Full), Capacity, Industry, Spot(label='Industry, Spot'), FixedRequirement, RandomRequirement(side_weights={East,West}); ConfigError(problems) lists ALL problems; rejects duplicate YAML keys (line no.), unknown fields (difflib 'did you mean'), position in config"
    db.py: "Database.open(path|':memory:', discard_other_version=False); transaction() (writes outside refused; no nesting; rollback on error); rows Session(day, flags west_chore_done, east_chore_done, westbound_in_yard, switch_westbound_done, westbound_in_west_staging, local_back, local_return_done, eastbound_in_yard, switch_eastbound_done, eastbound_in_east_staging, local_has_work; words next_chore_mode, west_chore_mode, east_chore_mode), Car(label), Engine(label), SpotState(fresh()), PlanEntry; CHECK constraints (world cars may have seq, engines in a world may not); unique index one car per spot; SCHEMA_VERSION=3 (user_version); car rows converted by position (_CAR_SELECT) for speed; clear_all(); remove_from_consist_plans(); set_consist_plan(train, engine_ids, car_ids)"
    reconcile.py: "spot_identity(spot); create_spot_states (cold start only); check_config(db, config) -> notes, raises ColdStartNeeded(reasons)"
    rosterfiles.py: "read_cars/read_engines(path) -> (rows, problems) with line numbers; engine_count_problems (MIN_ENGINES switcher 1, local 2, manifest 6); RosterFileError(problems)"
    coldstart.py: "cold_start(db, config, cars_path, engines_path, rng=None) -> notes; checks first; then clear_all, import, next_chore_mode = config chore_mode, create_spot_states, roll_ahead each spot, planning.plan_day (day 1 planned; day-1 West-supplied spots short, as expected; day-1 chores always full: no train order known)"
    roster.py: "retire_car (at spot -> bad_order=True; else removed + removed from plans), retire_engine, sync_roster(...) -> notes, where_is(config, kind, ref)"
    spots.py: "pure functions on (Spot config, SpotState): need(), upcoming_need(), next_draw_need() (random day-early draw) -> Need(car_type, direction, side, base_processing_days, delay_chance, idle_days); set_out(); pull(day, bad_order); advance(rng, settings, new_day, frozen); preview_advance(new_day) (countdowns with prerolled delay, no rolls, disruption ignored); roll_ahead(); SpotRuleError"
    forecast.py: "pure: for_today(config, states, day, bad_order_spots) / for_tomorrow(config, states, day, served_today, bad_order_spots) -> Forecast(day, demands, not_drawn); Demand(spot_id, car_type, direction, side, waiting_since_day, swap; load property); in_line(demands, rng) = oldest first, random ties. Raw spot demand only; netting vs Locals cars is planning"
    planning.py: "make_plan(config, day, states, cars, engines, rng, chore_mode=Full) pure -> DayPlan(today/tomorrow Forecast, today_supply/tomorrow_supply [Supply(demand, car_id, source)], westbound/eastbound/local TrainPlan(engine_ids, car_ids, block_ids, arriving, departing, overload), eastbound_draw, eastbound_minimum, westbound_pickup, eastbound_pickup (predicted), assignments {car: (spot, load)}, released, going_home, local_has_work, notes, west_chore_mode, east_chore_mode); plan_day(db, config, rng) (inside a txn; uses session.next_chore_mode) = make + apply_plan (assignments + loads, releases, stale world assignments reset, consist plans, local_has_work, today's chore modes); outgoing_types(config); engines_needed(arriving, departing, settings); west_train(cars) = West staging cars with seq, reversed (yesterday's WB as an EB, head->rear); _Planner._quick(world) (falls back to Full with a note if no order known), _take_west (quick: fitting car already in the train first: Local block rearmost, East supply frontmost; else random spare), _swap_rear(train, block, east_supply, length)"
    signals.py: "handle(db, config, signal, spot_id=None, rng=None) -> notes = SINGLE ENTRY POINT, one txn per signal, SignalRefused (plain message, nothing changed); _JOBS = {flag: (job, refusal name, needs)} dependency map (each signal waits only for its needs; refusal names the jobs workable now, 'Waiting on X.'; Eastbound in yard before Local return job: 'The eastbound can't enter the yard until the Local return job is done.'); open_jobs(session) -> [jobs] (chores alone until both done; Eastbound to yard open from chores on; Session complete when all done); accepts(session, signal); set_chore_mode(db, mode) -> notes (next_chore_mode; refused if not Full/Quick); effects per Section 13; _arrive keeps train order as world seq (cars already there -> seq NULL); auto-skip local (no work at Switch westbound) and Local return job (nothing to sort/send home); session complete = day advance (days_held +1 for unassigned empties on Locals, spots.advance frozen if Bad order car at spot, plan_day) and resets every job flag"
    yardwork.py: "derived yard jobs: switch_westbound/switch_eastbound(db, config) -> YardJob(train, cut, pickup, left_behind, length_after, overload) (uses planned cars before the chore via train_cars()); local_return(db, config) -> [Move(car, track, reason)] (local's cars, then cars leaving Locals); toward(world)"
    worklists.py: "plain-text lists: chore_sheet(world) (Quick: title '  (Quick chore)' + car-move sections), switch_list(train), main_line_list(job) (route line 'From X to Y (N engines, M cars)'; WB to W staging bad-order line; EB to yard waits-in-siding line instead of button until Local return job done), local_list() (first line 'Pick up engines X and Y from storage.'), local_return_list(), spot_lines()/spot_text(), current_work() = lists of every open job joined by blank lines; local_work(db) -> LocalWork(pulls, pending, spotted); actions(db, config) -> [Action(label, signal, spot_id)] = buttons accepted now across all open jobs (set-out only once its spot is empty)"
    simulate.py: "simulate(config, cars, engines, days, seed, skip_chance, bad_order_chance, chore_mode=None [Full|Quick|Mixed; None = config]) -> Report (incl. chore_mode, quick_chores per world); format_report(report, config); InvariantBroken; checks after EVERY signal (car conservation except Bad order at W, E loop closed set both ways, staging capacities, spot<->car agreement, world cars untracked unless planned, Locals contents); quick chores: reused cars keep yesterday's order, Local block at rear, WB gains no cars; sends main-line signals (Westbound in West staging at a random point in the day); engines check allows +-1 vs actual lengths (plan uses predicted lengths); ~40 s per simulated year; never adds cars, so high bad-order chances deplete the roster (real retirements extremely rare per user)"
    cli.py: "main(argv) with subcommands simulate|play; play_loop(db, config, read, write, rng) (header '=== Day N — <open jobs> ===' + chore_mode_line 'Chores: full today; quick from the next day advance (c = change)'; numbered buttons; s spots, l all lists, c toggle chore mode, q quit); exit 1 on invariant broken / spot never served / cold start needed"
  samples: "samples/config.yaml: Northfield Paper (Loading door 1 boxcar Outgoing [East,East,West]; Loading door 2 boxcar Outgoing [West,East] idle 1; Chemical unloading tank car Incoming East), Harbor Feed Mill (Unloading pit covered hopper Incoming West idle 1; Bagged feed dock boxcar Outgoing [East]), Transfer Facility (Team track 1 flatcar Incoming East; Team track 2 Random: boxcar Incoming E/W, covered hopper Outgoing, tank car Incoming East). cars.csv 65 cars (16 East staging, 49 West staging; 5 flatcars; gondolas + autoracks = through-only). engines.csv 19 (14 manifest [3 in East staging], 4 local [1 with empty model], 1 switcher)."
  simulator_findings_sample_config: "365 days, full chores: eastbound_length_max 20 -> overload ~10% of days (WB longest 26); 18 -> ~1%; 16 -> 0%; no extra shortages. Quick chores roughly double overload days (seeds 3-5: full 21-42 days per manifest, quick 49-77; longest about the same 23-26). Spots wait <0.1 day avg; held empties ~45% reused. Team track 1 occasionally short (few flatcars). Decide real value with real industry config, in the chore mode mostly used."
  todo_later_steps:
    - "step 11: web page: main page = open_jobs + current_work + actions() buttons + spot_lines + chore mode toggle (set_chore_mode; show chore_mode_line text); printable chore sheets; edit tool (car location/load, spot state); Sync roster button, single add/retire; cold start (Database.open(discard_other_version=True))"
    - "step 11: the edit tool is also how a wrong signal is undone (no undo signal)"
    - "step 11: the edit tool must handle world seq (train order in staging): moving a car into/out of a world, or undoing an arrival signal, must keep seq consistent (car in a world: seq = place in the last arriving train, or NULL for spares)"

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
    6: "DONE forecast (forecast.py; property test: forecast == next day's real state)"
    7: "DONE train planning (planning.py; cold start plans day 1)"
    8: "DONE signals + daily sequence (signals.py, yardwork.py)"
    9: "DONE work lists + spot display text (worklists.py)"
    10: "DONE simulator CLI + play CLI (simulate.py, cli.py)"
    10a: "DONE 2026-11-13 (user hand-run; findings built: main-line signals + parallel jobs, local engines line, Full/Quick chores)"
  milestone_2_web:
    11: "NEXT: Flask web app (main page = open jobs + chore mode toggle, list, signal buttons, spot states; printable chore sheets; edit tool cars+spots; roster sync/add/retire; cold start import/reset)"
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
  lists: "moves only, never order (see moves_not_order_rule)"

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
  engine_shortage: not modeled (ample); planning notes it if it ever happens (only possible right after a cold start with odd engine locations)

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
    preroll: "at EVERY day advance (after transitions), for EVERY spot: Random draws next requirement (weight, then side weights) if none; next_delay rolled with chance of the requirement the spot will process next (upcoming_need). Roll used only if spot is Processing at next advance, else discarded. Cold start: random spot draws first requirement + all rolls."
    disruption: rolled at completion (not prerolled)
  bad_order_spot:
    freeze: "spot with Bad order car: advance(frozen=True) -> no countdowns"
    pull_from_Processing: "-> Awaiting car, original waiting_since (place in line), same requirement, no pattern advance"
    pull_from_Ready: "normal pull (work done; position already advanced; idle applies)"
  display: "one line per spot (worklists.spot_text): 'Awaiting car — needs a loaded covered hopper from the West [— CSXT 14420 waiting on the Locals track | on the local | coming on the eastbound manifest | coming from West staging]'; 'Awaiting car — needs an empty boxcar to load for the East'; 'Processing CSXT 14420 (tank car) — 2 days left' (bad order: '— bad order, waiting for the local'); 'Ready for pickup: X (boxcar), loaded for the West' | ', empty' | ', bad order'; 'Idle — 1 day before it wants a car again'; random undrawn: 'next need not drawn yet'"
  incoming: needs loaded car of type from source dir; pulled -> empty
  outgoing: needs empty; pulled -> loaded, dest already fixed at Ready
  random_mode: no position; fresh E/W roll per draw
  shortage: oldest-waiting first (waiting_since_day), random tiebreak; unserved stays Awaiting, rolls forward
  local_visit: one per industry per day, pull+spot combined
  pull_before_setout: "setout on an occupied spot only after its pull_done; separate signals (pull alone OK if no replacement car). The ONLY ordering rule for the local."
  config_vs_state: config static; runtime state persists, never reset on reload

worlds:
  rebuilt: before every session (chore)
  loads_inside: "Not tracked (except planned Local-block cars, which get load + assigned_spot when chosen)"
  E: closed set = exactly cars of prior EB manifest; re-sorted via yard tracks (full chore) or only Local block moved to rear (quick chore), never mixed with yard cars; nothing added/removed; all ride out; rebuild ends with train back in loop for step 1
  W: pool; EB built from any staging cars (full chore) or yesterday's WB reversed + rear swap (quick chore); rest stay as spares; WB arrival couples onto spares OK

loads:
  tracked_only_for: local-bound/local-originated cars; continuing + world cars = Not tracked
  assign_at: "Local-block selection (planning time): incoming spot -> Loaded; outgoing spot -> Empty (CONFIRMED 2026-11-11)"
  undelivered: keeps assigned load
  return_to_shipper: if target industry == last_loaded_at -> must be Empty (outgoing spot only); applies to world cars and predicted pickup cars
  pulled_cars: keep real load on Eastbound/Westbound tracks; -> Not tracked on entering world

supply_to_spots:
  incoming: loaded car from spot's source world (fixed source | rolled source)
  outgoing_empty:
    1: held empty of type on Locals track first, any origin; longest-held first
    2: "else from world == scheduled destination (shuttle): dest W -> empty from W staging (EB local block); dest E -> empty from E loop (WB local block)"
    scheduled_dest: "fixed: pattern[position] (pre-disruption); random: dest rolled at draw"
    disruption: rolled at completion; may ship to other side than supplied from; accepted
  choice_among_fitting_cars: "random (CONFIRMED 2026-11-11); quick West chore: fitting car already in yesterday's train first (Local block rearmost, East supply frontmost), else random spare (user, 2026-11-13)"
  undelivered_car: back to Locals via Local return job, keeps assigned_spot, first in line next run; forecast/planning counts spot as covered

routing_pulled_cars:
  loaded_from_outgoing: Eastbound|Westbound track per dest fixed at Ready
  empty_from_incoming:
    if_type_used_by_any_outgoing_spot_and_N_gt_0: "hold on Locals (days_held 0); day advance +1 for unassigned empties on Locals; usable while days_held <= N (default 2): pulled Mon -> usable Tue, Wed -> goes home at Thu's Local return job"
    else: immediately -> track toward origin_world
  expired_held_empty: "Local return job moves it Locals -> track toward origin_world (CONFIRMED 2026-11-11)"
  stray_assigned_car: "car on Locals assigned to a spot whose need now/upcoming/next-draw no longer matches its type+load -> released (assigned_spot cleared): holdable empty -> held empty; else home via Local return job (CONFIRMED 2026-11-11)"
  bad_order: -> Westbound track always; removed from roster when WB arrives West staging

train_building:
  local_blocks_demand_driven:  # computed at day advance from forecast, net of held empties + undelivered cars on Locals
    WB_block: serves TODAY's E-supplied demand (set out step 2, spotted same day)
    EB_block: serves TOMORROW's W-supplied demand (set out step 7, spotted next day)
  local_block: rear; filled from ANY matching-type car available in that world (prior role irrelevant); order WITHIN block never planned (operator's choice)
  continuing: random order ahead of local block (full chore); quick chore keeps yesterday's order
  WB_continuing: all WB cars not in local block continue to W staging (Switch westbound cuts local block only)
  WB_length: fixed = E closed set (yesterday's EB arrival in E)
  EB_length:
    draw: random int [eastbound_length_min, eastbound_length_max], config defaults 12, 20; counted LEAVING W staging (before yard work)
    floor: "local_block + tomorrow's E-supply cars not covered by Eastbound pickup (predicted = today's pulls headed E + cars going home E at Local return job); draw raised to floor"
    cap: W staging cars available, and East loop capacity
    continuing_pick: E-supply cars + random filler from W pool; unchosen stay as spares
  E_supply: EB (+ its Eastbound pickup) must carry cars for TOMORROW's E-supplied demand; cars only guaranteed by type here, assigned to spots tomorrow from the E loop
  post_yard_length: "arriving - setout + pickup; ENTIRE pickup track always taken; >20 -> exception overload train"
  overload_propagates: EB overload -> next day's WB same size (E closed set); WB may exceed 20 after Switch westbound too; same rule
  overflow_safeguard: "only if E loop (~30) or W staging capacity would be exceeded -> oldest pickups first, rest wait a day (CONFIRMED as spec 2026-11-11; trimming EB filler rejected). W room counted with EB still in W staging."
  leftover_engines: both worlds -> storage at chore
  chore_modes:  # user, 2026-11-13 (step 10a)
    names: [Full, Quick]  # Full = rebuild as above
    setting: "config settings.chore_mode (default Full) = mode after cold start; main-page toggle (signals.set_chore_mode; not a signal) sets session.next_chore_mode; used at the NEXT day advance (today's chores already planned stay); one mode for both worlds"
    quick_E: "WB = EB cars in arrival order (world seq), Local block moved to rear; nothing added/removed"
    quick_W: "EB = yesterday's WB reversed (planning.west_train); length = clamp(len, eastbound_length_min, max), raised to minimum, capped by W pool + E capacity; rearmost unneeded cars off to spare tracks (E-supply cars stay anywhere); on at rear: E-supply spares, then random filler spares, then Local block last (_swap_rear)"
    quick_car_choice: "fitting car already in yesterday's train first, so no like-for-like swap (Local block: rearmost fitting; East supply: frontmost fitting); else random spare; Local block car from mid-train sorted to rear"
    engines: regular rules in both modes (reusing engines reversed via engine escape REJECTED)
    after_cold_start: "no train order known -> that world gets a full chore, with planning note 'Quick chore not possible in <West staging|the East loop> today: no train order is known there yet, so it gets a full chore.'"
    effect: quick roughly doubles overload days (keeps length instead of drawing)
  retired_planned_car: train runs one car short (removed from consist_plan)

forecast:
  E_supplied_for_day_D: chosen from cars sent E on day D-1 EB; set out D step2 before local -> same-day spot
  W_supplied: EB set out at step7 after local -> spotted next day
  direction: incoming = source; outgoing (no held empty) = scheduled destination
  needs_a_car_on_day: "Awaiting car; Ready for pickup with idle 0 (swap, waiting from that day); Processing with Bad order car (pull frees it, keeps place in line)"
  inputs: industry config + spot state + assigned/undelivered cars + prerolls (spots.upcoming_need, next_delay); no extra config
  assumes: today's local completes all listed moves; deviations self-correct next forecast
  shortages: accepted; self-correct ~next day
  not_drawn: "random spot refilled today, Ready again tomorrow with idle 0 (base 1): next requirement not drawn yet -> listed not_drawn, no car planned, waits ~1 day (ACCEPTED 2026-11-11; draw-two-ahead + forbidding rejected)"

daily_sequence:  # jobs in usual order; after both chores, jobs run in parallel: each signal waits only for its needs (user, 2026-11-13)
  0: "pre-session chores (rebuild WB in E loop via yard tracks; rebuild EB in W staging; engine moves; Full or Quick)  [West chore done, East chore done; either order]"
  1: "Westbound to yard: WB leaves E loop -> main in yard  [Westbound in yard; needs both chores]"
  2: "Switch westbound: Local block -> Locals; Westbound track -> train  [Switch westbound done; needs Westbound in yard]"
  3: "Westbound to West staging  [Westbound in West staging; needs Switch westbound; parallel with 4-8; Bad order cars aboard leave roster here]"
  4: "local job; leaves returned cars on main  [Pull done(spot), Set-out done(spot), Local back in yard; needs Switch westbound]; auto-skipped if no local work (checked live at Switch westbound)"
  5: "Local return job: local's cars -> Eastbound|Westbound|Locals; undelivered -> Locals; expired held empties/released cars Locals -> home track  [Local return job done; needs Local back]; auto-skipped if nothing to do"
  6: "Eastbound to yard: EB leaves W staging -> main in yard; job OPEN from both chores on (parallel with 1-5; waits in a passing siding), signal REFUSED until Local return job done  [Eastbound in yard; needs both chores + Local return job]"
  7: "Switch eastbound: Local block -> Locals; Eastbound track -> train  [Switch eastbound done; needs Eastbound in yard]"
  8: "Eastbound to East staging: EB -> E loop, overnight  [Eastbound in East staging; needs Switch eastbound]"
  end: "session_complete == day advance; needs every job"
  facts: "WB pickup = yesterday's pulls; EB pickup = today's pulls; E loop empty at 1, filled at 8; a train joins its staging only at its arrival signal; both chores before either manifest moves (user chose over per-train)"
signals:
  names: [West chore done, East chore done, Westbound in yard, Switch westbound done, Westbound in West staging, Pull done, Set-out done, Local back in yard, Local return job done, Eastbound in yard, Switch eastbound done, Eastbound in East staging, Session complete]  # matched ignoring capitals/spaces; job names 'X to Y', arrival signals 'X in Y' (user's choice)
  input_layer: single entry point (signals.handle) for all signals; sources = web page now, ESP32/MQTT later; core agnostic
  chore_main_line_and_yard_jobs: binary done/not-done, no partial
  main_line_signals: "Westbound in yard / Eastbound in yard: no record change (switch job may start); Westbound in West staging / Eastbound in East staging: train dissolves into world, cars keep train order as seq (cars already there -> seq NULL)"
  chore_mode_toggle: not a signal; any time; affects next day advance only
  local: per-move Pull done / Set-out done (per spot) + manual Local back in yard
  no_signal: didn't happen (unpulled car stays on spot, Ready, keeps dest; unset-out car stays on local -> Local return job returns it to Locals)
  local_cars_on_local_from: Switch westbound done
  local_back: closes local; unsignalled setouts = not delivered; produces Local return job list (or skips the job)
  local_return_done: applies sort; Switch eastbound pickup list final
  ordering: "each signal accepted once the jobs it needs are done (signals._JOBS); otherwise refused 'Waiting on <jobs workable now>.' e.g. 'Waiting on Switch westbound.'; Eastbound in yard before Local return job -> 'The eastbound can't enter the yard until the Local return job is done.'; chores either order; page shows every open job; local moves ANY order across/within industries; only refusal = set-out on occupied spot ('Pull X from <spot> first.'); refused signal changes nothing"
  session_complete: requires every job done (both chores, 4 main-line jobs, Switch westbound, Local return job, Switch eastbound; skipped counts as done); performs day advance (held days, spot advance with bad-order freeze, day-ahead rolls, plan_day in next_chore_mode); resets all job flags
  pause: power-off/stop anytime = pause; resume at the open jobs with exact state
  chore_mismatch: "planned car/engine not where plan expects -> left out with a note (CONFIRMED 2026-11-11)"
  local_engines: "Storage -> Local at Switch westbound; -> Storage at Local return job (CONFIRMED 2026-11-11)"

outputs:
  produced_at_day_advance: [chore sheets, Switch westbound list, local list, Switch eastbound provisional]
  produced_live: {local_return_list: on Local back in yard, switch_eastbound_pickup_final: on Local return job done}
  derived_always: "every list is computed from records when shown (worklists.py)"
  medium: web page (primary); chore sheets printable; CLI play mode for testing
  chore_sheet_per_world: {sections: ["1 engines storage->staging", "2 engines staging->storage", "3 train list: engines lead-first; cars head->rear numbered; local-block cars show 'Loaded|Empty -> <industry> (Local block)'"], quick_west: "title + '  (Quick chore)'; 3 'Cars off the train → spare tracks:', 4 'Cars from the spare tracks → train:', 5 'Cars moved to the rear of the train (Local block):', 6 train list", quick_east: "3 'Cars moved to the rear of the train (Local block):', 4 train list", car_names: "'<mark number> <type>' comma-separated", empty_section: "prints 'none'", after_signal: "✓ done"}
  yard_jobs: "ONE list per job of moves grouped by from->to, no order, no reasons: 'Move N cars from the main to the Locals track: <mark number type, ...>'; 'Move N cars from the Westbound track to the main: ...'; Local return job also 'from the main to the Eastbound|Westbound track' and 'from the Locals track to the ...'; Bad order car tagged '(bad order)'; overload note '(Train leaves with N cars — exception overload train)' only when final; Switch eastbound before Local return job: '(More cars may reach the Eastbound track during the Local return job.)'; car names never split across lines"
  main_line: "'<TRAIN> — <job>' then '  From East staging to the main in the yard (N engines, M cars)' (routes: E staging->main in yard, yard->W staging, W staging->main in yard, yard->E staging); WB to W staging adds '  Bad order, take off the layout in West staging: X.' when any; EB to yard shows '  May leave West staging now, but waits in a passing siding until the Local return job is done.' instead of its button until accepted; done -> '✓ done'"
  local: "first line '  Pick up engines X and Y from storage.' (no run back: local ends day in storage); per industry: 'Pull <car> (<type>, loaded|empty|bad order) <- <spot>  [Pull done]' / 'Spot <car> (<type>, <load>) -> <spot>  [Set-out done]' + '(after pull)' when that spot has a pull; done set-out marked '✓ done'; done pull leaves industry section -> 'PULLED, BACK TO THE YARD: <car> -> <next track>' (pulled-from spot never stored/shown)"
  buttons: "worklists.actions: signals accepted now across all open jobs; set-out button only once its spot is empty"
  open_jobs: "page/CLI shows every open job's list (worklists.current_work)"

corrections_persistence:
  edit_tool: anytime; set car location + load; set spot state (state, days_left, out_dest, position); also undoes mistaken signals; never via physical buttons
  persist: every signal + edit saved immediately (SQLite), one transaction each
  cold_start:
    when: once, on deliberate reset, or when config industries/spots change structurally (see data_model.config.changes)
    checks: "both CSVs fully checked first (line-numbered problems); staging capacity; engine minimums; any problem -> nothing changes; warning per spot no roster car can serve"
    effect: "clear all; day 1; cars in listed world (origin = that world, load Not tracked); engines Storage|world; every spot Awaiting car (random draws first requirement) + day-early rolls; yard empty; day 1 planned (plan_day)"
    other_version_db: replaced (Database.open(discard_other_version=True))
  roster_changes:  # NEVER need a cold start; via web page
    sync_roster: "re-read cars.csv + engines.csv (files = master list in git): new car -> added, WEST STAGING ONLY; new engine -> added at listed location; missing car/engine -> retired; existing car keeps place; car TYPE CAN NEVER CHANGE -> refused; existing engine takes file pool + model; capacity + engine minimums checked; any problem -> nothing changes"
    single_add_retire: also available on web page
    retire_car_at_spot: "marked Bad order: next local pulls it '(bad order)', Local return job -> Westbound track, leaves roster when WB reaches West staging; spot frozen until pull"
    retire_car_elsewhere: "removed at once (take off layout); removed from consist_plan (train runs one short); if assigned to a spot, spot gets replacement at next planning"
    retire_engine: removed at once (+ from consist_plan)

data_model:
  principle: store decisions + current positions only; derive everything else on demand (lists never drift)
  impl: Python, stdlib sqlite3, no ORM
  config:  # YAML file (e.g. config.yaml), hand-edited, in git, static at runtime
    settings: {hold_days_on_locals: 2, eastbound_length_min: 12, eastbound_length_max: 20, train_nominal_max: 20, three_engines_from: 16, delay_chance_max: 1, chore_mode: Full, capacity: {east_staging: 30, west_staging: 70, yard_track: 35}}  # each optional -> default; eastbound_length_max to be tuned with simulator (see open)
    industries: "[{id, name, spots: [section-5 spot schema; spot_id internal, name shown]}]"
    optional_defaults: {disruption_chance: 0, delay_chance: 0, idle_days: 0, weight: 1}
    limits: ["base_processing_days >= 1", "delay_chance < 1", "chances 0..1", "eastbound_length_min <= eastbound_length_max <= capacity.east_staging", "weights >= 0 with at least one > 0", "weight > 0"]
    names: industry names unique; spot names unique WITHIN an industry; spot_id unique across file
    errors: "ConfigError lists ALL problems: '<Industry>, <Spot>: <problem>'; unknown field -> 'did you mean'; duplicate YAML key -> line number; position in config refused"
    changes:
      need_cold_start: [industry/spot added or removed, id or spot_id changed, spot mode/car type/direction changed, random possible_requirements list changed (added/removed, car type or direction)]
      no_cold_start: [names, settings, processing days, chances, idle days, weights, patterns (shorter pattern -> position wraps)]
      mechanism: "spot_state stores industry_id + identity at cold start; check_config at start-up compares (identity compared ignoring capitals) and refuses with all reasons"
    car_types: free text; match ignoring capitals/spacing
  tables:
    session: "single row: day; flags 0/1: west_chore_done, east_chore_done, westbound_in_yard, switch_westbound_done, westbound_in_west_staging, local_back, local_return_done, eastbound_in_yard, switch_eastbound_done, eastbound_in_east_staging, local_has_work; words Full|Quick (CHECK): next_chore_mode (toggle), west_chore_mode, east_chore_mode (today's, set at planning); open jobs derived from flags"
    car: "id, mark, number (unique mark NOCASE + number), type, loc_kind, loc_ref, seq, load, last_loaded_industry, origin_world, assigned_spot, dest_world, days_held, bad_order"
    engine: "id, mark, number, model(opt), pool(Local|Switcher|Manifest), loc_kind, loc_ref, seq"
    spot_state: "spot_id, industry_id, identity, state, days_left, position, requirement_number (1-based), requirement_side, out_dest, waiting_since_day, next_delay, next_requirement_number, next_requirement_side"
    consist_plan: "train(Westbound manifest|Eastbound manifest|Local), seq, car_id|engine_id (exactly one; FK); written at day advance; applied by West chore done / East chore done / Switch westbound done (Local); cleared next day advance"
    integrity: "CHECK constraints enforce plain words + per-kind location rules; unique index = one car per spot; schema version via PRAGMA user_version = 3 (older db -> cold start)"
  locations:  # shared by car + engine; values are plain language
    World: {ref: [East staging, West staging], seq: "cars: place in the train that last arrived there (1 = behind engines), for quick chores; spares NULL; engines: unused", note: "East staging = hidden return loop"}
    Yard: {ref: [Eastbound track, Westbound track, Locals track], seq: arrival order (oldest first), cars_only: true}
    Spot: {ref: spot_id (displayed by spot name), seq: unused, cars_only: true}
    Train: {ref: [Westbound manifest, Eastbound manifest, Local], seq: "head->rear; engines lead first"}
    Storage: {ref: Storage, engines_only: true}
    W_staging: pool only; no per-track tracking
    train_lifetime: "manifest: chore signal -> arrival signal (Westbound in West staging / Eastbound in East staging; dissolves into world); LOCAL: Switch westbound done -> Local return job done"
  derived_not_stored: [local block = manifest cars with assigned_spot, Switch westbound/eastbound pickup = whole track at job time (Switch eastbound provisional before Local return job), local list = Ready spots + Bad order cars + Local plan cars, Local return job moves (section 8 rules + cars leaving Locals), chore-sheet engine moves = plan vs current location, quick chore car moves = yesterday's train vs plan, open jobs = from session flags, spot display text, forecast, buttons (actions), capacity/length checks]
  csv:
    cars: "mark,number,type,location  (location East staging|West staging)"
    engines: "mark,number,model,pool,location  (pool Local|Switcher|Manifest; location Storage|East staging|West staging)"
    required: all columns except engine model (may be empty)
    parsing: "column names/locations/pools ignore capitals; any column order; blank lines skipped; marks stored CAPITALS; UTF-8 (BOM ok); problems with line numbers"
    example: ["CSXT,14420,boxcar,West staging", "BNSF,7710,ES44AC,Manifest,Storage"]
  backups: none (loss -> cold start)

platform:
  brain: Python on Raspberry Pi
  db: SQLite
  ui: web page served over Wi-Fi; any browser; first client = old Android tablet (browser only); plain HTML, minimal JS
  ui_contents: spot states, open jobs, work lists, signal buttons, chore mode toggle, edit tool, roster sync/add/retire, cold start
  future: ESP32 nodes + push buttons + LCDs over MQTT become PRIMARY signal input; tablet = companion
  hardware_design: TBD, non-blocking (must send Section-13 signals; show spot states + open jobs)

open:
  - industry configs (spot counts ind1-3; ind4 existence) — data, needed before first real session, not before coding
  - eastbound_length_max — tune with simulator once real industry config exists (sample config: 20 -> ~10% overload days, 18 -> ~1%, 16 -> 0%; quick chores ~double overload days)
  - hardware node design — non-blocking
  - Android tablet OS version (browser compatibility) — minor

rejected:
  - v2 random daily schedule (order/count)
  - v2 weekday/weekend schedule variants
  - demand-aware arrival injection (superseded by worlds supplying empties)
  - Locals track capacity warning
  - JMRI, spreadsheet
  - drawing random requirements two days ahead / forbidding base-1 idle-0 random requirements
  - trimming EB random filler to make room in a full E loop
  - planning car order in Local blocks or on the local (incl. grouping by industry)
  - storing/showing the spot a pulled car came from
  - yard lists as numbered steps or with per-car reasons; separate sections in the Local return job list
  - each manifest leaving after its own chore (both chores first instead)
  - quick chore reusing engines reversed via engine escape; a third chore mode ('Simple') for it

confirmed_2026-11-08:
  - strict signal ordering (later job refused while earlier pending)
  - local's set-out cars count as on the local from Switch westbound done
  - Switch eastbound pickup list finalized at Local return job done
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
  - structural config change -> cold start; tuning changes don't
  - roster changes never need cold start; Sync roster; new cars West staging only; engine minimums 1/2/6; marks stored in capitals
  - Bad order lifecycle (retire at spot -> pulled -> Westbound track -> leaves roster at West staging; spot frozen; Processing pull keeps place in line; Ready pull normal)
  - retired car elsewhere/engine -> removed at once; planned train runs short
  - spot timing (delay holds 1 day, stacking; base 1 -> Ready next day; idle 1 -> Awaiting next day; idle 0 -> Awaiting at pull); delay preroll every spot every advance
  - (after v1.42) forecast not-drawn random case accepted
  - (after v1.42) expired held empties go home via Local return job; stray assigned cars released
  - (after v1.42) E loop overflow: spec safeguard kept (oldest pickups first)
  - (after v1.42) random choice among fitting cars; loads + assigned_spot set at selection; W room counted with EB in W staging
  - (after v1.42) operators choose all switching order; lists give moves only
  - (after v1.42) switcher job names Switch westbound / Local return job / Switch eastbound; signals '<name> done'
  - (after v1.42) local moves any order (only set-out-after-own-pull)
  - (after v1.42) Local return job auto-skipped when empty; EB may leave W staging early, can't enter yard until Local return job done
  - (after v1.42) chore mismatch -> left out with note; local work rechecked at Switch westbound; local engines to Storage at Local return job
  - (after v1.42) Switch eastbound pickup shown provisional; overload note only when final; spot lines show days left
  - (after v1.42) yard jobs = one list grouped from->to, no order, no reasons
  - (after v1.42) pulled car shown only by where it goes next

confirmed_2026-11-13:  # step 10a feedback
  - "main-line jobs 'Westbound to yard', 'Westbound to West staging', 'Eastbound to yard', 'Eastbound to East staging' with signals 'Westbound in yard', 'Westbound in West staging', 'Eastbound in yard', 'Eastbound in East staging'"
  - "both chores before either manifest moves"
  - "jobs parallel: Westbound to West staging alongside local..Eastbound to East staging; Eastbound to yard from chores on, enters yard only after Local return job"
  - "local list first line 'Pick up engines X and Y from storage.'; no run back (local ends day in storage)"
  - "chore modes Full / Quick (names chosen by user); config default + main-page toggle effective next day advance; both worlds; engines regular rules"
  - "quick W: reuse yesterday's WB reversed, keep length clamped to 12-20, swap at rear, Local block last; quick E: arrival order, Local block to rear"
  - "quick chore car choice: cars already in the train first (Local block rearmost, East supply frontmost), else random spare"
  - "simulator roster depletion under high bad-order chance is a simulator artifact only (real retirements extremely rare)"

derived_not_explicitly_confirmed:
  - "simulator engine-count check tolerance +-1 (plan uses predicted lengths)"
  - "days_held: pulled empty starts 0; +1 at each day advance while unassigned on Locals"
  - "quick W length lowered to W pool size and E loop capacity, as in full"
  - "day 1 after cold start: full chores with a note (no train order known)"
```
