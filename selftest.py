#!/usr/bin/env python3
"""End-to-end checks for the Twelf/LF slicer.

Set TWELF_SERVER to the twelf-server executable, for example:

    TWELF_SERVER=/tmp/twelf-src/bin/twelf-server python3 selftest.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from twelf_slicer.slicer import (
    SlicerError,
    check_text,
    exact_closure,
    line_count,
    parse_signature,
    reduction,
    render,
    run_twelf_check,
    statement_closure,
)
from twelf_slicer.trace import apply_trace, collect_trace

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus"

CASES = [
    ("nat.elf", "p_s"),
    ("list.elf", "append_cons"),
    ("bool.elf", "not_t"),
    ("definitions.elf", "two"),
    ("infix.elf", "impe"),
    ("false_positive.elf", "target"),
    ("chain.elf", "target"),
    ("judgment.elf", "of_app"),
]

# This case defeats the source-level identifier fallback: the bound variable
# shadows the top-level constant, but the free occurrence is a real dependency.
TRACE_ONLY_CASES = [("scope_capture.elf", "target")]


def main() -> int:
    server = os.environ.get("TWELF_SERVER")
    if not server:
        print("TWELF_SERVER is not set", file=sys.stderr)
        return 2

    use_trace = "--trace" in sys.argv[1:]
    label = "trace+" if use_trace else ""
    print(f"{'file':22} {'target':14} {'mode':10} {'lines':>12} {'red.':>7}  check")
    print("-" * 78)
    reductions = {"exact": [], "statement": []}
    failures = 0

    cases = CASES + (TRACE_ONLY_CASES if use_trace else [])
    for filename, target in cases:
        source = (CORPUS / filename).read_text(encoding="utf-8")
        sig = parse_signature(source)
        before = line_count(source)

        original = run_twelf_check(CORPUS / filename, server=server)
        if not original.ok:
            print(f"{filename}: original does not check", file=sys.stderr)
            print(original.output, file=sys.stderr)
            failures += 1
            continue

        if use_trace:
            try:
                trace, _ = collect_trace(CORPUS / filename, server=server)
                apply_trace(sig, trace)
            except SlicerError as exc:
                print(f"{filename}: trace failed: {exc}", file=sys.stderr)
                failures += 1
                continue

        for mode, closure in (("exact", exact_closure), ("statement", statement_closure)):
            keep = closure(sig, target)
            sliced = render(sig, keep, mode)
            after = line_count(sliced)
            pct = reduction(before, after)
            reductions[mode].append(pct)
            result = check_text(sliced, server=server)
            ok = "OK" if result.ok else "FAIL"
            print(
                f"{filename:22} {target:14} {label + mode:10} "
                f"{before:>5} -> {after:<3} {pct:>6.1f}%  {ok}"
            )
            if not result.ok:
                failures += 1
                print(result.output, file=sys.stderr)

    print("-" * 78)
    for mode, values in reductions.items():
        if values:
            print(
                f"{mode:10} mean reduction: {sum(values) / len(values):.1f}% "
                f"(range {min(values):.1f}%..{max(values):.1f}%)"
            )

    if failures:
        print(f"{failures} failure(s)", file=sys.stderr)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
