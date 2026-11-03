"""A small, dependency-directed slicer for Twelf/LF signatures.

The prototype does not try to re-implement LF type checking.  It parses a
Twelf signature, builds a declaration graph from the identifiers that occur in
types and definition bodies, computes a closure from a target declaration, and
renders a smaller signature.  ``twelf-server`` is used as the final oracle.

The important LF-specific detail is that constructors belong to a type family.
For an exact slice we keep all constructors of every kept type family, because
a logic program is not complete without its rules.  A statement slice keeps
only declarations needed to state the target, and drops definition/proof
bodies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
from typing import Iterable, Sequence


IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")
BINDER_RE = re.compile(r"[\[{]\s*([A-Za-z_][A-Za-z0-9_']*)\s*(?::|[\]}])")
DECL_HEAD_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_']*)\s*(?::|=)")
KEYWORDS = {"type"}


class SlicerError(RuntimeError):
    """Raised for malformed signatures, unknown targets, or failed checks."""


# ---------------------------------------------------------------------------
# Lexing and parsing
# ---------------------------------------------------------------------------


def strip_comments(text: str) -> str:
    """Remove Twelf comments while preserving newlines.

    Twelf comments are ``%`` followed by whitespace or another ``%`` (line
    comment), or ``%{ ... }%`` (nested block comment).  Other ``%`` tokens are
    directives such as ``%mode`` and are kept.
    """

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != "%":
            out.append(ch)
            i += 1
            continue

        nxt = text[i + 1] if i + 1 < n else ""
        if nxt == "{":
            depth = 1
            i += 2
            while i < n and depth:
                if text.startswith("%{", i):
                    depth += 1
                    i += 2
                elif text.startswith("}%", i):
                    depth -= 1
                    i += 2
                else:
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
            continue

        if nxt == "%" or nxt.isspace() or nxt == "":
            while i < n and text[i] != "\n":
                i += 1
            if i < n:
                out.append("\n")
                i += 1
            continue

        # A directive such as %mode, %name, %infix, ...
        out.append(ch)
        i += 1

    return "".join(out)


def split_blocks(text: str) -> list[str]:
    """Split a comment-free signature at top-level periods."""

    blocks: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch == ".":
            block = "".join(current).strip()
            if block:
                blocks.append(block)
            current = []
        else:
            current.append(ch)
    rest = "".join(current).strip()
    if rest:
        raise SlicerError(f"unterminated declaration near: {rest[:80]!r}")
    return blocks


def _matching_delimiter(text: str, start: int) -> int:
    """Return the index just after the delimiter matching text[start]."""

    pairs = {"(": ")", "{": "}", "[": "]"}
    opening = text[start]
    closing = pairs[opening]
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return i + 1
    raise SlicerError(f"unmatched {opening!r} in {text!r}")


def split_top_level(text: str, needle: str) -> tuple[str, str] | None:
    """Split at the first top-level occurrence of ``needle``."""

    depth = 0
    pairs = {"(": ")", "{": "}", "[": "]"}
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in pairs:
            depth += 1
        elif ch in pairs.values():
            depth -= 1
        elif depth == 0 and text.startswith(needle, i):
            return text[:i], text[i + len(needle) :]
        i += 1
    return None


def _strip_outer_parens(text: str) -> str:
    text = text.strip()
    while text.startswith("("):
        end = _matching_delimiter(text, 0)
        if end != len(text):
            break
        text = text[1:-1].strip()
    return text


def _strip_leading_binders(text: str) -> str:
    text = text.strip()
    while text and text[0] in "{[":
        end = _matching_delimiter(text, 0)
        text = text[end:].strip()
    return text


def _top_level_arrow_positions(text: str, arrow: str) -> list[int]:
    depth = 0
    pairs = {"(": ")", "{": "}", "[": "]"}
    positions: list[int] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in pairs:
            depth += 1
        elif ch in pairs.values():
            depth -= 1
        elif depth == 0 and text.startswith(arrow, i):
            positions.append(i)
            i += len(arrow)
            continue
        i += 1
    return positions


def type_head(type_text: str) -> str | None:
    """Return the head constant of an LF type/kind, or ``None``.

    ``A <- B <- C`` has result ``A``; ``A -> B -> C`` has result ``C``.
    Leading Pi binders are ignored.  ``type`` is returned for kinds.
    """

    text = _strip_outer_parens(type_text)
    text = _strip_leading_binders(text)
    if not text:
        return None

    left_arrows = _top_level_arrow_positions(text, "<-")
    if left_arrows:
        segment = text[: left_arrows[0]]
    else:
        right_arrows = _top_level_arrow_positions(text, "->")
        segment = text[right_arrows[-1] + 2 :] if right_arrows else text

    segment = _strip_outer_parens(segment)
    segment = _strip_leading_binders(segment)
    match = IDENT_RE.search(segment)
    return match.group(0) if match else None


def bound_names(text: str) -> set[str]:
    return {m.group(1) for m in BINDER_RE.finditer(text) if m.group(1) != "_"}


def identifiers(text: str) -> set[str]:
    return {m.group(0) for m in IDENT_RE.finditer(text) if m.group(0) not in KEYWORDS}


@dataclass
class Block:
    text: str
    kind: str  # "decl" or "directive"
    name: str | None = None
    directive: str | None = None
    type_text: str = ""
    body_text: str = ""
    is_abbrev: bool = False
    refs_type: set[str] = field(default_factory=set)
    refs_body: set[str] = field(default_factory=set)
    is_type_family: bool = False
    owner: str | None = None
    index: int = 0

    @property
    def refs(self) -> set[str]:
        return self.refs_type | self.refs_body


def parse_block(text: str, index: int) -> Block:
    stripped = text.strip()
    is_abbrev = False
    if stripped.startswith("%abbrev"):
        is_abbrev = True
        stripped = stripped[len("%abbrev") :].strip()
    elif stripped.startswith("%"):
        directive = stripped[1:].split(None, 1)[0] if len(stripped) > 1 else ""
        return Block(text=stripped, kind="directive", directive=directive, index=index)

    match = DECL_HEAD_RE.match(stripped)
    if not match:
        raise SlicerError(f"cannot parse declaration: {text[:100]!r}")
    name = match.group(1)
    rest = stripped[match.end() :].strip()

    # The head regex consumed ':' or '='.  Recover which one.
    head_text = stripped[: match.end()]
    if ":" in head_text:
        type_text = rest
        body_text = ""
        split = split_top_level(type_text, "=")
        if split is not None:
            type_text, body_text = split[0].strip(), split[1].strip()
    else:
        type_text = ""
        body_text = rest

    return Block(
        text=("%abbrev " + stripped) if is_abbrev else stripped,
        kind="decl",
        name=name,
        type_text=type_text,
        body_text=body_text,
        is_abbrev=is_abbrev,
        index=index,
    )


@dataclass
class Signature:
    blocks: list[Block]
    declarations: dict[str, Block]
    constructors: dict[str, list[str]]
    logic_families: set[str]

    @property
    def names(self) -> list[str]:
        return list(self.declarations)


def _merge_split_definitions(blocks: list[Block]) -> list[Block]:
    """Merge ``c : A.`` followed by ``c = M.`` into one block.

    Twelf allows a constant to be declared and defined in two separate
    declarations.  Treating them as one block is important for both closure
    and rendering: the statement slice can keep the type and drop the body.
    """

    by_name: dict[str, Block] = {}
    merged: list[Block] = []
    for block in blocks:
        if (
            block.kind == "decl"
            and block.name
            and not block.type_text
            and block.body_text
            and block.name in by_name
            and by_name[block.name].type_text
            and not by_name[block.name].body_text
        ):
            type_block = by_name[block.name]
            type_block.body_text = block.body_text
            type_block.text = f"{type_block.name} : {type_block.type_text} = {block.body_text}"
            continue
        merged.append(block)
        if block.kind == "decl" and block.name:
            by_name[block.name] = block
    return merged


def parse_signature(text: str) -> Signature:
    raw_blocks = split_blocks(strip_comments(text))
    blocks = _merge_split_definitions([parse_block(b, i) for i, b in enumerate(raw_blocks)])
    declarations = {
        b.name: b for b in blocks if b.kind == "decl" and b.name and b.name != "_"
    }

    # Resolve references only against declared names.  Bound variables are
    # removed separately, so uppercase free variables never become edges.
    for block in blocks:
        b_type = bound_names(block.type_text)
        b_body = bound_names(block.body_text)
        block.refs_type = identifiers(block.type_text) - b_type
        block.refs_body = identifiers(block.body_text) - b_body
        if block.kind == "decl":
            head = type_head(block.type_text)
            block.is_type_family = head == "type"
            block.owner = None
            if head and head in declarations and declarations[head].is_type_family:
                block.owner = head

    # Directives only contribute dependencies if they mention declared names.
    for block in blocks:
        if block.kind == "directive":
            block.refs_type = identifiers(block.text)
        block.refs_type &= declarations.keys()
        block.refs_body &= declarations.keys()

    constructors: dict[str, list[str]] = {}
    for block in blocks:
        if block.kind == "decl" and block.owner:
            constructors.setdefault(block.owner, []).append(block.name)  # type: ignore[arg-type]

    logic_families: set[str] = set()
    for block in blocks:
        if block.kind == "directive" and block.directive == "mode":
            logic_families.update(block.refs_type)

    return Signature(
        blocks=blocks,
        declarations=declarations,
        constructors=constructors,
        logic_families=logic_families,
    )


# ---------------------------------------------------------------------------
# Closures
# ---------------------------------------------------------------------------


def exact_closure(sig: Signature, target: str) -> set[str]:
    """Keep all type/body dependencies and all constructors of kept families."""

    keep: set[str] = set()
    work = [target]
    while work:
        name = work.pop()
        if name in keep or name not in sig.declarations:
            continue
        keep.add(name)
        block = sig.declarations[name]
        work.extend(block.refs)
        if block.is_type_family and name in sig.logic_families:
            # A logic program is incomplete without all of its rules.
            work.extend(sig.constructors.get(name, []))
        if block.owner and block.owner in sig.logic_families:
            work.append(block.owner)
            work.extend(sig.constructors.get(block.owner, []))
    return keep


def statement_closure(sig: Signature, target: str) -> set[str]:
    """Keep only what is needed for the target's statement.

    Definition bodies are dropped during rendering, so only type references
    are followed.  A declaration without a type cannot be made opaque; its body
    is therefore followed as well.
    """

    keep: set[str] = set()
    work = [target]
    while work:
        name = work.pop()
        if name in keep or name not in sig.declarations:
            continue
        keep.add(name)
        block = sig.declarations[name]
        work.extend(block.refs_type)
        if not block.type_text:
            work.extend(block.refs_body)
    return keep


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


SYNTAX_DIRECTIVES = {"name", "infix", "prefix", "postfix"}


def _render_decl(block: Block, mode: str) -> str:
    assert block.name
    if mode == "statement" and block.type_text and block.body_text:
        # The LF analogue of replacing a proof body with Admitted: keep the
        # type, make the constant opaque.
        return f"{block.name} : {block.type_text}."
    return block.text + "."


def _keep_directive(block: Block, mode: str, keep: set[str]) -> bool:
    if block.kind != "directive":
        return False
    if mode == "statement":
        return block.directive in SYNTAX_DIRECTIVES and block.refs_type <= keep
    return block.refs_type <= keep


def render(
    sig: Signature,
    keep: set[str],
    mode: str = "exact",
    *,
    selected: set[int] | None = None,
    header: str | None = None,
) -> str:
    if mode not in {"exact", "statement"}:
        raise SlicerError(f"unknown mode: {mode}")

    lines: list[str] = []
    if header:
        lines.append(f"%% {header}")
        lines.append("")

    for block in sig.blocks:
        if selected is not None and block.index not in selected:
            continue
        if block.kind == "decl":
            if block.name not in keep:
                continue
            lines.append(_render_decl(block, mode))
            lines.append("")
        else:
            if _keep_directive(block, mode, keep):
                lines.append(block.text + ".")
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Twelf oracle
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    ok: bool
    output: str
    command: list[str]


def compiler_command(path: str | None = None) -> list[str]:
    """Return the twelf-server command.  Only a single executable is needed."""

    candidate = path or os.environ.get("TWELF_SERVER") or shutil.which("twelf-server")
    if not candidate:
        raise SlicerError(
            "twelf-server not found. Install Twelf, put it on PATH, or set "
            "TWELF_SERVER=/path/to/twelf-server."
        )
    return [candidate]


def run_twelf_check(path: str | Path, server: str | None = None, timeout: int = 60) -> CheckResult:
    path = Path(path).resolve()
    cmd = compiler_command(server)
    payload = f"loadFile {path}\nquit\n"
    try:
        proc = subprocess.run(
            cmd,
            input=payload,
            text=True,
            capture_output=True,
            timeout=timeout,
            cwd=str(path.parent),
        )
    except FileNotFoundError as exc:
        raise SlicerError(f"cannot run {cmd[0]!r}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SlicerError(f"twelf-server timed out after {timeout}s") from exc

    output = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0 and "%% ABORT %%" not in output
    return CheckResult(ok=ok, output=output, command=cmd)


def check_text(text: str, server: str | None = None, timeout: int = 60) -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="twelf-slice-") as tmp:
        path = Path(tmp) / "slice.elf"
        path.write_text(text, encoding="utf-8")
        return run_twelf_check(path, server=server, timeout=timeout)


# ---------------------------------------------------------------------------
# Minimization and graph export
# ---------------------------------------------------------------------------


def minimize(
    sig: Signature,
    keep: set[str],
    mode: str,
    target: str,
    server: str | None = None,
    timeout: int = 60,
) -> tuple[str, set[int]]:
    """Greedily remove blocks while the Twelf oracle still accepts the slice.

    This is typecheck-minimal, not proof-semantics-minimal: a declaration may
    be removable for type checking and still be needed by the logic program.
    """

    target_blocks = {b.index for b in sig.blocks if b.name == target}
    selected = {b.index for b in sig.blocks if b.name in keep or _keep_directive(b, mode, keep)}

    # The target itself should remain present.  If there are several target
    # blocks (duplicate names), keep all of them.
    current = render(sig, keep, mode, selected=selected)
    result = check_text(current, server=server, timeout=timeout)
    if not result.ok:
        raise SlicerError("initial slice does not pass Twelf check:\n" + tail(result.output))

    # Try directives and non-target declarations, in reverse source order.
    for block in reversed(sig.blocks):
        if block.index not in selected:
            continue
        if block.index in target_blocks:
            continue
        candidate_selected = selected - {block.index}
        candidate = render(sig, keep, mode, selected=candidate_selected)
        result = check_text(candidate, server=server, timeout=timeout)
        if result.ok:
            selected = candidate_selected

    return render(sig, keep, mode, selected=selected), selected


def write_dot(sig: Signature, keep: set[str], path: str | Path) -> None:
    lines = ["digraph twelf_slice {", "  rankdir=LR;", "  node [shape=box, fontname=Menlo];"]
    for name in sorted(keep):
        block = sig.declarations[name]
        shape = "ellipse" if block.is_type_family else "box"
        lines.append(f'  "{name}" [shape={shape}];')
    for name in sorted(keep):
        block = sig.declarations[name]
        for ref in sorted(block.refs_type & keep):
            lines.append(f'  "{ref}" -> "{name}" [label="type"];')
        for ref in sorted(block.refs_body & keep):
            lines.append(f'  "{ref}" -> "{name}" [label="body", style=dashed];')
        if block.owner and block.owner in keep:
            lines.append(f'  "{block.owner}" -> "{name}" [label="owner", style=dotted];')
    lines.append("}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mermaid(sig: Signature, keep: set[str], path: str | Path) -> None:
    lines = ["flowchart LR"]
    for name in sorted(keep):
        lines.append(f'  {name}["{name}"]')
    for name in sorted(keep):
        block = sig.declarations[name]
        for ref in sorted(block.refs_type & keep):
            lines.append(f"  {ref} -->|type| {name}")
        for ref in sorted(block.refs_body & keep):
            lines.append(f"  {ref} -.->|body| {name}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def line_count(text: str) -> int:
    return len([line for line in text.splitlines() if line.strip()])


def reduction(before: int, after: int) -> float:
    return 0.0 if before == 0 else 100.0 * (before - after) / before


def tail(text: str, n: int = 40) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])
