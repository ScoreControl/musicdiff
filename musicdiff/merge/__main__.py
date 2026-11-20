# ------------------------------------------------------------------------------
# Purpose:       CLI entry point (`score-merge`) for 3-way merging and 2-way
#                selective cherry-picking across MuseScore (.mscz / .mscx) files.
# ------------------------------------------------------------------------------
"""CLI tool for merging MuseScore (.mscz / .mscx) scores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Tuple

from musicdiff.merge.archive_merger import cherry_pick_scores, merge_scores
from musicdiff.merge.models import MergeConflict


def _parse_measure_range(spec: str) -> Tuple[int, int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return int(a), int(b)
    n = int(spec)
    return n, n


def _interactive_resolver(conflict: MergeConflict) -> str:
    print("\n--- MERGE CONFLICT ---")
    print(f"Layer:    {conflict.layer}")
    print(f"Location: {conflict.location}")
    print(f"Details:  {conflict.description}")
    if conflict.base_summary is not None:
        print(f"  base:   {conflict.base_summary}")
    if conflict.ours_summary is not None:
        print(f"  ours:   {conflict.ours_summary}")
    if conflict.theirs_summary is not None:
        print(f"  theirs: {conflict.theirs_summary}")

    while True:
        ans = input("Choose resolution [o=ours, t=theirs, b=base, s=skip/unresolved]: ").strip().lower()
        if ans in ("o", "ours"):
            return "ours"
        if ans in ("t", "theirs"):
            return "theirs"
        if ans in ("b", "base"):
            return "base"
        if ans in ("s", "skip", ""):
            return "unresolved"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="score-merge",
        description=(
            "Merge MuseScore (.mscz / .mscx) files via 3-way merge "
            "(base + ours + theirs) or 2-way selective cherry-pick."
        ),
    )
    parser.add_argument(
        "scores",
        nargs="+",
        type=Path,
        help="3-way merge: BASE OURS THEIRS. With --cherry-pick: SOURCE TARGET.",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        required=True,
        help="Output .mscz or .mscx file path",
    )
    parser.add_argument(
        "--strategy",
        choices=("fail", "ours", "theirs", "base"),
        default="fail",
        help="Conflict resolution strategy for 3-way merge (default: fail)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt interactively for each merge conflict",
    )
    parser.add_argument(
        "--conflict-report",
        type=Path,
        help="Write structured JSON conflict report to this path",
    )
    parser.add_argument(
        "--write-on-conflict",
        action="store_true",
        help="Write output file even when unresolved conflicts exist (defaults conflicting hunks to ours)",
    )
    parser.add_argument(
        "--cherry-pick",
        action="store_true",
        help="2-way selective mode: copy --layers and/or --measures from SOURCE onto TARGET",
    )
    parser.add_argument(
        "--layers",
        nargs="+",
        choices=("audio", "style", "metadata", "automation"),
        default=[],
        help="Proprietary layers to copy in --cherry-pick mode",
    )
    parser.add_argument(
        "--measures",
        type=str,
        help="1-based inclusive measure or range (e.g., '12' or '12-16') for --cherry-pick",
    )
    parser.add_argument(
        "--staff",
        type=str,
        default=None,
        help="Optional staff id (e.g., '1') to scope --measures in --cherry-pick mode",
    )

    args = parser.parse_args()

    if args.cherry_pick:
        if len(args.scores) != 2:
            parser.error("--cherry-pick requires exactly 2 score paths: SOURCE TARGET")
        measure_range: Optional[Tuple[int, int]] = (
            _parse_measure_range(args.measures) if args.measures else None
        )
        if not args.layers and measure_range is None:
            parser.error("--cherry-pick requires at least one of --layers or --measures")
        result = cherry_pick_scores(
            source=args.scores[0],
            target=args.scores[1],
            output_path=args.output,
            layers=args.layers,
            measure_range=measure_range,
            staff_id=args.staff,
        )
    else:
        if len(args.scores) != 3:
            parser.error("3-way merge requires exactly 3 score paths: BASE OURS THEIRS")
        result = merge_scores(
            base=args.scores[0],
            ours=args.scores[1],
            theirs=args.scores[2],
            output_path=args.output,
            strategy=args.strategy,
            resolver=_interactive_resolver if args.interactive else None,
            write_on_conflict=args.write_on_conflict,
        )

    print(result.format_report())

    if args.conflict_report is not None:
        args.conflict_report.parent.mkdir(parents=True, exist_ok=True)
        args.conflict_report.write_text(
            json.dumps(result.to_dict(), indent=2), encoding="utf-8"
        )
        print(f"Saved conflict report to: {args.conflict_report}")

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
