"""Twelf/LF proof-slicing prototype."""

from .trace import Trace, apply_trace, collect_trace, parse_trace
from .slicer import (
    CheckResult,
    Signature,
    SlicerError,
    check_text,
    compiler_command,
    exact_closure,
    line_count,
    minimize,
    parse_signature,
    reduction,
    render,
    run_twelf_check,
    statement_closure,
    write_dot,
    write_mermaid,
)

__all__ = [
    "CheckResult",
    "Signature",
    "SlicerError",
    "check_text",
    "compiler_command",
    "exact_closure",
    "line_count",
    "minimize",
    "parse_signature",
    "reduction",
    "render",
    "run_twelf_check",
    "statement_closure",
    "write_dot",
    "write_mermaid",
    "Trace",
    "apply_trace",
    "collect_trace",
    "parse_trace",
]

__version__ = "0.2.0"
