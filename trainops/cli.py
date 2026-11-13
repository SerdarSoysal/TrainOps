"""Command line: `python -m trainops <command>`.

    simulate   play many days automatically and report (development step 10)
    play       run sessions by hand, one signal at a time (step 10a)

Run `python -m trainops <command> --help` for the options.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Callable
from pathlib import Path

from trainops import vocab as v
from trainops.coldstart import cold_start
from trainops.config import ConfigError, load_config
from trainops.db import Database, DatabaseError
from trainops.reconcile import ColdStartNeeded, check_config
from trainops.rosterfiles import RosterFileError
from trainops.signals import SignalRefused, handle, open_jobs, set_chore_mode
from trainops.simulate import format_report, simulate
from trainops.worklists import (
    actions,
    chore_sheet,
    current_work,
    local_list,
    local_return_list,
    main_line_list,
    spot_lines,
    switch_list,
)

SAMPLES = Path("samples")


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    parser = argparse.ArgumentParser(prog="python -m trainops", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    sim = commands.add_parser("simulate", help="play many days automatically and report")
    _roster_options(sim)
    sim.add_argument("--days", type=int, default=365, help="days to play (default 365)")
    sim.add_argument("--seed", type=int, default=1, help="random seed (same seed, same run)")
    sim.add_argument("--skip-chance", type=float, default=0.0,
                     help="chance the local skips each move, 0 to 1 (default 0)")
    sim.add_argument("--bad-order-chance", type=float, default=0.0,
                     help="chance per day that a car at a spot is retired as Bad order")
    sim.add_argument("--chore-mode", choices=["full", "quick", "mixed"], type=str.lower,
                     default=None, help="chores: full, quick, or mixed (changed at random "
                     "each day); default: the configuration's chore_mode")

    play = commands.add_parser("play", help="run sessions by hand, one signal at a time")
    _roster_options(play)
    play.add_argument("--db", default="trainops.db", help="saved state (default trainops.db)")
    play.add_argument("--cold-start", action="store_true",
                      help="start over from the roster files (clears the saved state)")

    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "simulate":
            return _simulate(args, config)
        return _play(args, config)
    except (ConfigError, RosterFileError, DatabaseError, FileNotFoundError) as problem:
        print(problem)
        return 1


def _roster_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=SAMPLES / "config.yaml", type=Path,
                        help="configuration file (default samples/config.yaml)")
    parser.add_argument("--cars", default=SAMPLES / "cars.csv", type=Path,
                        help="car roster file (default samples/cars.csv)")
    parser.add_argument("--engines", default=SAMPLES / "engines.csv", type=Path,
                        help="engine roster file (default samples/engines.csv)")


def _utf8_output() -> None:
    """Print arrows and dashes correctly in the Windows console and when piped."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


# --- simulate --------------------------------------------------------------------------


def _simulate(args, config) -> int:
    report = simulate(config, args.cars, args.engines, args.days, args.seed,
                      args.skip_chance, args.bad_order_chance, args.chore_mode)
    print(format_report(report, config))
    return 1 if report.broken or report.never_served else 0


# --- play ------------------------------------------------------------------------------

HELP = ("Type a number to send that signal; s = spots, l = all lists, "
        "c = change chore mode, q = quit.")


def _play(args, config) -> int:
    db = Database.open(args.db, discard_other_version=args.cold_start)
    try:
        if args.cold_start:
            for note in cold_start(db, config, args.cars, args.engines):
                print(note)
        else:
            try:
                for note in check_config(db, config):
                    print(note)
            except ColdStartNeeded as problem:
                print(problem)
                print("Run again with --cold-start to start over from the roster files.")
                return 1
        play_loop(db, config, input, print)
    finally:
        db.close()
    return 0


def play_loop(db: Database, config, read: Callable[[str], str], write: Callable[[str], None],
              rng: random.Random | None = None) -> None:
    """Show the open jobs and their buttons; send the signal typed. Ends on q or end of input."""
    rng = rng or random.Random()
    show = True
    while True:
        session = db.session()
        buttons = actions(db, config)
        if show:
            write("")
            write(f"=== Day {session.day} — {', '.join(open_jobs(session))} ===")
            write(chore_mode_line(session))
            write(current_work(db, config))
            write("")
            for number, act in enumerate(buttons, 1):
                write(f"  {number:>2}  {act.label}")
            write(HELP)
        show = True
        try:
            answer = read("> ").strip().lower()
        except EOFError:
            return
        if answer in ("q", "quit", "exit"):
            return
        if answer == "s":
            write("\n".join(spot_lines(db, config)))
            show = False
        elif answer == "l":
            write(_all_lists(db, config))
            show = False
        elif answer == "c":
            other = v.CHORE_QUICK if session.next_chore_mode == v.CHORE_FULL else v.CHORE_FULL
            for note in set_chore_mode(db, other):
                write(note)
            show = False
        elif answer.isdigit() and 1 <= int(answer) <= len(buttons):
            act = buttons[int(answer) - 1]
            try:
                for note in handle(db, config, act.signal, act.spot_id, rng):
                    write(note)
            except SignalRefused as refusal:
                write(f"Refused: {refusal}")
        else:
            write(HELP)
            show = False


def chore_mode_line(session) -> str:
    """Today's chore modes and the toggle's setting for the next day advance."""
    west, east = session.west_chore_mode, session.east_chore_mode
    today = west.lower() if west == east else \
        f"{west.lower()} in West staging, {east.lower()} in the East loop"
    return (f"Chores: {today} today; {session.next_chore_mode.lower()} from the next "
            f"day advance (c = change)")


def _all_lists(db: Database, config) -> str:
    parts = [
        chore_sheet(db, config, v.WEST_STAGING),
        chore_sheet(db, config, v.EAST_STAGING),
        main_line_list(db, config, v.WESTBOUND_TO_YARD),
        switch_list(db, config, v.WESTBOUND_MANIFEST),
        main_line_list(db, config, v.WESTBOUND_TO_WEST_STAGING),
        local_list(db, config),
        local_return_list(db, config),
        main_line_list(db, config, v.EASTBOUND_TO_YARD),
        switch_list(db, config, v.EASTBOUND_MANIFEST),
        main_line_list(db, config, v.EASTBOUND_TO_EAST_STAGING),
    ]
    return "\n\n".join(parts)


if __name__ == "__main__":
    sys.exit(main())
