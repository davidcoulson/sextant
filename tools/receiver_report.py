#!/usr/bin/env python3
"""
Which receivers earn their place?

Reads the election log and, for every placed receiver, says how often it was
part of the elected floor's fix and how its ranges sat against that fix:

``heard``  cycles it was among the elected floor's proxies.
``bias``   median of (its range - its distance to the fix), in metres. A
           receiver that always reads long or short is miscalibrated or
           misplaced; near zero is good.
``off``    median of the absolute difference: bias and noise together.

The fix is built from these same ranges, so a receiver pulls the fix towards
agreeing with it: the figures understate a bad receiver, most of all where
few others hear the thing. A fingerprint-only fix did not use the ranges at
all but is counted the same. Worst bias first.

Usage::

    python tools/receiver_report.py config/sextant_election_log --layout config/.storage/sextant
    python tools/receiver_report.py log/ --layout layout.json --hours 24 --min 50
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from replay_cross_floor import load_layout, load_rows  # noqa: E402

# The report itself is the integration's (the Health page shows it too); loaded
# by path so this tool needs no Home Assistant.
_spec = importlib.util.spec_from_file_location("sextant_receiver_report", os.path.join(HERE, "..", "custom_components", "sextant", "receiver_report.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
report, silent, thing_height = _mod.report, _mod.silent, _mod.thing_height


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("log", help="the election log directory, or one of its files")
    ap.add_argument("--layout", required=True, help="the layout (config/.storage/sextant or a snapshot)")
    ap.add_argument("--hours", type=float, help="only the last N hours of the log")
    ap.add_argument("--min", type=int, default=20, help="leave out receivers heard in fewer cycles (20)")
    args = ap.parse_args(argv)
    layout = load_layout(args.layout)
    lines = report(load_rows(args.log, args.hours), layout)
    print(f"{'floor':16}{'receiver':44}{'heard':>8}{'bias m':>8}{'off m':>10}")
    for floor, slug, n, bias, off in lines:
        if n >= args.min:
            print(f"{str(floor)[:15]:16}{slug[:43]:44}{n:>8}{bias:>+8.2f}{off:>10.2f}")
    quiet = silent(lines, layout)
    if quiet:
        print(f"\nNever in an elected floor's fix ({len(quiet)}): " + ", ".join(slug for _f, slug in quiet))


if __name__ == "__main__":
    main()
