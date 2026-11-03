"""Typing-derivation trace support.

The stock Twelf server does not expose the constants that the type checker
visits.  The accompanying patch (``patches/twelf-slice-trace.patch``) adds a
small ``SliceTrace`` structure to Twelf and writes a TSV file when
``TWELF_SLICE_TRACE`` is set.

This module runs the patched server and merges the resulting edges into a
parsed :class:`~twelf_slicer.slicer.Signature`.  The source-level parser is
still used for declaration text and directives; the dependency edges, however,
come from the type checker rather than from identifier matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import tempfile

from .slicer import Signature, SlicerError, compiler_command, tail


@dataclass
class Trace:
    decls: dict[str, str] = field(default_factory=dict)  # name -> kind
    refs_type: dict[str, set[str]] = field(default_factory=dict)
    refs_body: dict[str, set[str]] = field(default_factory=dict)
    raw: str = ""

    def merge(self, other: "Trace") -> None:
        for name, kind in other.decls.items():
            self.decls.setdefault(name, kind)
        for target, refs in other.refs_type.items():
            self.refs_type.setdefault(target, set()).update(refs)
        for target, refs in other.refs_body.items():
            self.refs_body.setdefault(target, set()).update(refs)
        self.raw += other.raw


def parse_trace(text: str) -> Trace:
    trace = Trace(raw=text)
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        tag, left, right = parts
        if tag == "decl":
            trace.decls[left] = right
        elif tag == "type":
            trace.refs_type.setdefault(left, set()).add(right)
        elif tag == "body":
            trace.refs_body.setdefault(left, set()).add(right)
    return trace


def collect_trace(
    path: str | Path,
    server: str | None = None,
    timeout: int = 60,
) -> tuple[Trace, str]:
    """Run the patched Twelf server and return (trace, server output)."""

    path = Path(path).resolve()
    cmd = compiler_command(server)
    with tempfile.TemporaryDirectory(prefix="twelf-trace-") as tmp:
        trace_path = Path(tmp) / "trace.tsv"
        env = os.environ.copy()
        env["TWELF_SLICE_TRACE"] = str(trace_path)
        payload = f"loadFile {path}\nquit\n"
        try:
            import subprocess

            proc = subprocess.run(
                cmd,
                input=payload,
                text=True,
                capture_output=True,
                timeout=timeout,
                cwd=str(path.parent),
                env=env,
            )
        except FileNotFoundError as exc:
            raise SlicerError(f"cannot run {cmd[0]!r}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SlicerError(f"twelf-server timed out after {timeout}s") from exc

        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0 or "%% ABORT %%" in output:
            raise SlicerError("Twelf rejected the input:\n" + tail(output))
        if not trace_path.exists():
            raise SlicerError(
                "twelf-server did not produce a trace. Is this the patched "
                "twelf-server with TWELF_SLICE_TRACE support?"
            )
        trace = parse_trace(trace_path.read_text(encoding="utf-8"))
        if not trace.decls:
            raise SlicerError("twelf-server produced an empty trace")
        return trace, output


def apply_trace(sig: Signature, trace: Trace) -> Signature:
    """Replace source-level dependency edges with type-checker edges."""

    known = set(sig.declarations)
    for block in sig.blocks:
        if block.kind != "decl" or not block.name:
            continue
        name = block.name
        if name not in trace.decls:
            # The trace may not contain block declarations or anonymous
            # definitions.  Leave their source-level edges in place.
            continue
        kind = trace.decls[name]
        block.is_type_family = kind == "type_family"
        type_refs = trace.refs_type.get(name, set()) & known
        body_refs = trace.refs_body.get(name, set()) & known
        block.refs_type = type_refs
        block.refs_body = body_refs - type_refs

    # Owner/constructor tables are derived from the (now traced) declaration
    # kinds and the source-level type head.
    constructors: dict[str, list[str]] = {}
    for block in sig.blocks:
        if block.kind != "decl" or not block.name:
            continue
        if block.owner and block.owner in sig.declarations:
            if sig.declarations[block.owner].is_type_family:
                constructors.setdefault(block.owner, []).append(block.name)
    sig.constructors = constructors
    return sig
