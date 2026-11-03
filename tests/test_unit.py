from __future__ import annotations

import unittest

from twelf_slicer.slicer import (
    bound_names,
    exact_closure,
    line_count,
    parse_signature,
    reduction,
    render,
    statement_closure,
    strip_comments,
    type_head,
)


PLUS = """\
nat : type.
z : nat.
s : nat -> nat.

plus : nat -> nat -> nat -> type.
%mode plus +X +Y -Z.
p_z : plus z Y Y.
p_s : plus (s X) Y (s Z) <- plus X Y Z.
%worlds () (plus X Y Z).
%total X (plus X Y Z).

even : nat -> type.
even_z : even z.
"""


class ParsingTests(unittest.TestCase):
    def test_strip_comments_keeps_directives(self) -> None:
        text = "%% line\nnat : type. %{ block %{ nested }% still }%\n%mode plus +X -Y.\n"
        stripped = strip_comments(text)
        self.assertIn("nat : type.", stripped)
        self.assertIn("%mode plus +X -Y.", stripped)
        self.assertNotIn("line", stripped)
        self.assertNotIn("block", stripped)

    def test_type_head(self) -> None:
        self.assertEqual(type_head("type"), "type")
        self.assertEqual(type_head("nat -> nat -> type"), "type")
        self.assertEqual(type_head("plus (s X) Y (s Z) <- plus X Y Z"), "plus")
        self.assertEqual(type_head("nat -> nat"), "nat")
        self.assertEqual(type_head("{X:nat} nat"), "nat")

    def test_bound_names(self) -> None:
        self.assertEqual(bound_names("{X:nat} [Y:nat] plus X Y"), {"X", "Y"})

    def test_parse_and_closures(self) -> None:
        sig = parse_signature(PLUS)
        self.assertIn("plus", sig.logic_families)
        self.assertIn("p_z", sig.constructors["plus"])
        self.assertIn("p_s", sig.constructors["plus"])

        exact = exact_closure(sig, "p_s")
        self.assertEqual(exact, {"nat", "z", "s", "plus", "p_z", "p_s"})
        statement = statement_closure(sig, "p_s")
        self.assertEqual(statement, {"nat", "s", "plus", "p_s"})

        exact_text = render(sig, exact, "exact")
        self.assertIn("%total X (plus X Y Z).", exact_text)
        self.assertIn("p_z : plus z Y Y.", exact_text)

        statement_text = render(sig, statement, "statement")
        self.assertNotIn("p_z", statement_text)
        self.assertNotIn("%total", statement_text)


    def test_false_positive_bound_variable(self) -> None:
        sig = parse_signature(
            """\
nat : type.
z : nat.
s : nat -> nat.
helper : nat.
target : nat -> nat = [helper:nat] s helper.
unused : nat.
"""
        )
        keep = exact_closure(sig, "target")
        self.assertNotIn("helper", keep)
        self.assertNotIn("unused", keep)
        self.assertIn("target", keep)

    def test_split_definition_is_merged(self) -> None:
        sig = parse_signature(
            """\
nat : type.
z : nat.
target : nat.
target = z.
"""
        )
        target = sig.declarations["target"]
        self.assertEqual(target.type_text, "nat")
        self.assertEqual(target.body_text, "z")
        self.assertIn("target", exact_closure(sig, "target"))


    def test_line_reduction(self) -> None:
        self.assertEqual(reduction(10, 5), 50.0)
        self.assertEqual(line_count("a.\n\nb.\n"), 2)
        self.assertEqual(reduction(0, 0), 0.0)


if __name__ == "__main__":
    unittest.main()
