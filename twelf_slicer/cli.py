"""Command-line interface for the Twelf/LF slicer."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .slicer import (
    SlicerError,
    check_text,
    exact_closure,
    line_count,
    minimize,
    parse_signature,
    reduction,
    render,
    run_twelf_check,
    statement_closure,
    tail,
    write_dot,
    write_mermaid,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="twelf-slice",
        description="Slice a Twelf/LF signature from a target declaration.",
    )
    p.add_argument("file", type=Path, help="Twelf .elf signature")
    p.add_argument("target", nargs="?", help="target declaration name")
    p.add_argument(
        "--mode",
        choices=["exact", "statement", "skeleton"],
        default="exact",
        help="exact = all dependencies + constructors; statement/skeleton = type-only",
    )
    p.add_argument("-o", "--output", type=Path, help="write sliced signature here (default: stdout)")
    p.add_argument("--dot", type=Path, help="write dependency graph as DOT")
    p.add_argument("--mermaid", type=Path, help="write dependency graph as Mermaid")
    p.add_argument("--minimize", action="store_true", help="greedily remove blocks while Twelf accepts the result")
    p.add_argument("--server", help="path to twelf-server (default: $TWELF_SERVER or PATH)")
    p.add_argument("--no-check", action="store_true", help="do not run twelf-server on the slice")
    p.add_argument("--check-input", action="store_true", help="check the original file before slicing")
    p.add_argument("--list", action="store_true", help="list declarations and exit")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        source = args.file.read_text(encoding="utf-8")
        sig = parse_signature(source)
    except FileNotFoundError:
        print(f"twelf-slice: no such file: {args.file}", file=sys.stderr)
        return 2
    except (OSError, SlicerError) as exc:
        print(f"twelf-slice: {exc}", file=sys.stderr)
        return 2

    if args.list:
        for block in sig.blocks:
            if block.kind == "decl" and block.name:
                mark = "type family" if block.is_type_family else f"constructor of {block.owner or '?'}"
                print(f"{block.name:24} {mark}")
        return 0

    if not args.target:
        print("twelf-slice: target declaration is required", file=sys.stderr)
        return 2

    if args.target not in sig.declarations:
        names = ", ".join(sig.names[:20])
        print(f"twelf-slice: unknown target {args.target!r}. Known names: {names}", file=sys.stderr)
        return 2

    if args.check_input and not args.no_check:
        result = run_twelf_check(args.file, server=args.server)
        if not result.ok:
            print("twelf-slice: input does not pass Twelf check:", file=sys.stderr)
            print(tail(result.output), file=sys.stderr)
            return 1

    mode = "statement" if args.mode == "skeleton" else args.mode
    if mode == "exact":
        keep = exact_closure(sig, args.target)
    else:
        keep = statement_closure(sig, args.target)

    selected: set[int] | None = None
    if args.minimize:
        if args.no_check:
            print("twelf-slice: --minimize requires Twelf checking", file=sys.stderr)
            return 2
        try:
            sliced, selected = minimize(
                sig, keep, mode, args.target, server=args.server
            )
        except SlicerError as exc:
            print(f"twelf-slice: {exc}", file=sys.stderr)
            return 1
    else:
        header = f"Sliced from {args.file.name} for target {args.target} ({mode})"
        sliced = render(sig, keep, mode, header=header)

    if args.output:
        args.output.write_text(sliced, encoding="utf-8")
    else:
        sys.stdout.write(sliced)

    if args.dot:
        write_dot(sig, keep, args.dot)
    if args.mermaid:
        write_mermaid(sig, keep, args.mermaid)

    before = line_count(source)
    after = line_count(sliced)
    if selected is None:
        decls_after = len(keep)
    else:
        decls_after = len(
            [
                b
                for b in sig.blocks
                if b.index in selected and b.kind == "decl" and b.name and b.name != "_"
            ]
        )
    print(
        f"twelf-slice: target={args.target} mode={mode} "
        f"decls={decls_after} lines={before}->{after} "
        f"(-{reduction(before, after):.1f}%)",
        file=sys.stderr if not args.output else sys.stdout,
    )

    if not args.no_check:
        result = check_text(sliced, server=args.server)
        stream = sys.stdout if args.output else sys.stderr
        if result.ok:
            print("twelf-slice: Twelf check OK", file=stream)
        else:
            print("twelf-slice: Twelf check FAILED", file=stream)
            print(tail(result.output), file=stream)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
