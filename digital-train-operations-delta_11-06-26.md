# DELTA 2026-11-06 vs checkpoint_7-13-26.md (AI-facing; terse)
Load order: checkpoint_7-13-26.md, then this. This file overrides conflicting checkpoint content. Session paused mid-topic; resume at PENDING.

## LAYOUT FACTS (new; user-supplied schematic, simplified)
- W=left, E=right. Single-track main. Passing sidings exist (omitted from schematic) -> meets non-issue. Aux small yard near Ind#1/#2 provides runarounds -> runaround non-issue.
- BUILT: Ind#1, Ind#2 (shared lead, spurs diverge toward W), Ind#3 transfer facility (spur diverges toward W), engine storage = 3 tracks, yard = 3 stub tracks (Eastbound, Westbound, Locals), ladder points at W end (tracks extend E, stub at E end), hidden E return loop (holds 1 train; max ~30 cars + 3 eng).
- PLANNED: main extension W, Ind#4 (uncertain; may be replaced by scenery; type/spots unknown), W end world rep.
- Only exact items in schematic: 3 yard tracks + E return loop.
- Yard switching occurs on main; acceptable (<=2 operators, no conflict).
- Capacities: max train 20 cars + 3 eng; E loop ~30 cars + 3 eng; yard tracks ~30-35 cars each.
- E loop: train can sit overnight. Hand-handling cars in loop possible but user refuses -> treat loops as hands-off (consist returns unchanged except software-notional load flips).
- Spot counts Ind#1-3: unknown.

## SUPERSEDED CHECKPOINT DECISIONS
- Sec1/9 "no individual car tracking" -> REVERSED: track individual cars (roster: id, road/num, type, load/empty, location). User motivation: solves design problems. Rationale confirmed: hands-off 1-train loops make "declared/ephemeral" arrivals physically impossible; arrival = what went in.
- Sec2/6 "single stub staging = whole world; E/W logical labels only" -> REVERSED: E and W are physical. E = hidden return loop (built). W = Option B single-track return loop (decided; no room for multi-track loop). Option A (stub staging, 2-4 trk, engine escape, rebuild trains) considered and rejected for construction simplicity.
- Sec6 "staging ephemeral/notional (Option B old)" -> REVERSED: worlds are stateful, capacity 1 train each, persists across sessions.
- Sec6 "staging capacity no scheduling pressure" -> REVERSED: loop capacity 1 => moves into each world must strictly alternate in/out.
- Sec7 v1 schedule template -> INVALID (violates E loop capacity: two E arrivals before any E departure). Replace (see SESSION PATTERN).
- Sec3/7 "breakdown trains" + "through trains engine swap" -> REPLACED by modern-practice model (user accepted): town = crew-change point + small yard on single-track secondary main with a based local. Manifests do set-out/pick-up of blocks (not full breakdown). Through trains change crews not engines. Engine storage = small servicing/based-power facility.
- Sec8 demand-driven arrival generation (arrival declared from demand tally) -> REPLACED: software plans what to SEND into a world; it returns next session. Demand planning becomes 1-day-ahead forecast.
- Through-only cars (e.g. steel coils, no matching industry) -> user accepts them shuttling; now modeled as permanent non-set-out blocks riding inside manifests (no slot for separate through trains).

## DEFINITIONS / OPS MECHANICS AGREED
- Manifest = mixed carload freight between yards; sets out/picks up blocks at intermediate yards. EB manifest: arrives from W, sets out Local block, keeps E-continuing cars, picks up Eastbound-track block, departs E. WB mirror. (User initially had direction mixed; corrected.)
- WB manifest (arrives from E) self-works yard: pull W past ladder, shove rear Local block into Locals track, shove into Westbound track, couple, pull out, depart. Requires Local block on REAR on arrival.
- EB manifest (arrives from W) cannot self-work (facing-point into stub tracks traps engines) -> switcher job required (switcher works train while it holds on main/siding, or set-out on siding W of yard). Local's engines may double as switcher (prototypical; fits <=2 operators).
- Job types now: WB manifest, EB manifest, switcher/yard job (possibly local crew), local. (Separate through trains: none under current capacity.)
- Dependency: EB manifest departure depends on switcher completing set-out/pick-up.
- Prototype notes given: modern Class I uses ex-mainline 6-axle (ES44/AC4400/Dash9/SD70) on locals/yards -> big modern power realistic. Alternatives evaluated: busy double-track main (poor fit), end-of-line terminal w/ turn (good but loses through traffic), unit-train hub (partial). Chosen: secondary-main crew-change point.

## SESSION PATTERN (proposed, implied by 2x 1-train loops; not yet formally confirmed)
Start: train X in E loop, Y in W loop.
1 Y exits W loop -> EB manifest -> yard work via switcher
2 X exits E loop -> WB manifest -> self-works yard (X,Y meet at siding)
3 local job
4 Y enters E loop; 5 X enters W loop. End: trains swapped ends, sit overnight.
=> ~2 road trains/session max unless "min one session away" relaxed.
Rule proposed: train entering a world stays out >= until next session (realism).

## NEW RULES / REQUIREMENTS
- Max train 20 cars + 3 eng (train builder constraint).
- Software must validate any schedule template vs world occupancy (capacity 1 each).
- Persistent state now includes: industries/spots, yard tracks, E loop consist, W loop consist, car roster locations, engine locations.
- Outbound trains planned 1 day ahead: car selection AND block order (Local block placement for next arrival: rear for WB-arriving train; EB-arriving placement per switcher access).
- Offline load flip: car entering a world can change load (empty->loaded / loaded->empty) => supplies loaded cars for incoming spots, absorbs surplus empties.
- Yard tracks act as real car inventory/buffer (30-35 cap vs 20-car trains): software picks which waiting cars ride out -> variety.
- Engine swaps on manifests at yard used for variety (disguise repeated consists); power from engine storage.
- Loop/stub distinction irrelevant to software; world model params = capacity, rebuildable(bool; false for loops), min_away_sessions.

## ISSUES I RAISED AT SESSION START (status)
1 Same-day resupply for incoming spots broken (demand tallied at arrival before local pulls) -> likely RESOLVED by 1-day-ahead forecast (must include spots expected to become empty, e.g. READY_FOR_PICKUP w/ cooldown 0). Verify when designing forecast.
2 Surplus empties accumulate in Local forever -> RESOLVED in principle by individual tracking + offline load flips (route empties out). Needs routing rule.
3 Sec2 says industries only flat/box/hopper & tankers never to Local, but Sec9 transfer facility has tanker+centerbeam spots -> UNRESOLVED; not yet discussed with user.
4 Random incoming spot source roll timing (must roll at draw/EMPTY time for planning) -> UNRESOLVED; still relevant (now for forecast).

## JMRI RE-EVAL (discussed)
Individual tracking removes main JMRI rejection reason. My assessment: JMRI lacks demand-driven planning, delay/disruption/pattern/cooldown/oldest-first mechanics, industry-centric jobs, button-flow fit. Offered middle path (cosmetic IDs) — superseded since user wants true tracking for design reasons. Implicitly: continue custom build. Not explicitly re-confirmed.

## PENDING (resume here)
- Q to user unanswered: are ~2 road trains/session enough, or allow occasional extra train (relax min-away rule => same consist visibly returns same session)?
- User still has more "what I want the system to do" to state; sanity-check against checkpoint+delta continues.
- Open design: car/block planning rules for outbound trains; offline load-flip rules; empty-car routing; forecast definition; engine assignment (old plan item 2); job sequencing formalization (old item 3, now required); Ind#4 existence; spot counts; issue 3 & 4 above; through/continuing car count config (old open item — now = which cars ride as permanent through block, size?).
- Hardware still deferred.
