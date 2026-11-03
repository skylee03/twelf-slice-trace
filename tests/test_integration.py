from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path

from twelf_slicer.slicer import (
    SlicerError,
    check_text,
    exact_closure,
    parse_signature,
    render,
    statement_closure,
)
from twelf_slicer.trace import apply_trace, collect_trace


ROOT = Path(__file__).resolve().parents[1]
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


def find_server() -> str | None:
    return os.environ.get("TWELF_SERVER") or shutil.which("twelf-server")


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = find_server()
        if not cls.server:
            raise unittest.SkipTest("twelf-server not found; set TWELF_SERVER")

    def test_corpus_exact_and_statement(self) -> None:
        for filename, target in CASES:
            source = (CORPUS / filename).read_text(encoding="utf-8")
            sig = parse_signature(source)
            for mode, closure in (
                ("exact", exact_closure),
                ("statement", statement_closure),
            ):
                keep = closure(sig, target)
                sliced = render(sig, keep, mode)
                result = check_text(sliced, server=self.server)
                self.assertTrue(
                    result.ok,
                    f"{filename}:{target}:{mode} failed:\n{result.output}",
                )

    def test_typing_trace_is_not_source_syntax(self) -> None:
        # This test only runs with the patched Twelf server that supports
        # TWELF_SLICE_TRACE.
        try:
            trace, _ = collect_trace(CORPUS / "nat.elf", server=self.server)
        except SlicerError as exc:
            self.skipTest(str(exc))

        # In the source, p_s only mentions plus and s.  The type checker also
        # infers nat for the implicit variables X/Y/Z.
        self.assertIn("nat", trace.refs_type["p_s"])
        source = parse_signature((CORPUS / "nat.elf").read_text(encoding="utf-8"))
        self.assertNotIn("nat", source.declarations["p_s"].refs_type)

        sig = parse_signature((CORPUS / "nat.elf").read_text(encoding="utf-8"))
        apply_trace(sig, trace)
        self.assertIn("nat", sig.declarations["p_s"].refs_type)
        for mode, closure in (
            ("exact", exact_closure),
            ("statement", statement_closure),
        ):
            sliced = render(sig, closure(sig, "p_s"), mode)
            self.assertTrue(check_text(sliced, server=self.server).ok)

    def test_trace_repairs_scope_capture(self) -> None:
        # The source-level parser sees the bound helper in the lambda and
        # removes *all* helper references, including the free one.  The trace
        # distinguishes the two occurrences.
        try:
            trace, _ = collect_trace(CORPUS / "scope_capture.elf", server=self.server)
        except SlicerError as exc:
            self.skipTest(str(exc))

        source = (CORPUS / "scope_capture.elf").read_text(encoding="utf-8")
        source_sig = parse_signature(source)
        source_keep = exact_closure(source_sig, "target")
        source_slice = render(source_sig, source_keep, "exact")
        self.assertNotIn("helper", source_keep)
        self.assertFalse(check_text(source_slice, server=self.server).ok)

        traced_sig = parse_signature(source)
        apply_trace(traced_sig, trace)
        traced_keep = exact_closure(traced_sig, "target")
        traced_slice = render(traced_sig, traced_keep, "exact")
        self.assertIn("helper", traced_keep)
        self.assertTrue(check_text(traced_slice, server=self.server).ok)


if __name__ == "__main__":
    unittest.main()
