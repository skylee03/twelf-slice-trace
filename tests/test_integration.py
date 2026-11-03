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


if __name__ == "__main__":
    unittest.main()
