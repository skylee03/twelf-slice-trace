# Design notes

## Why LF/Twelf?

The Rocq prototype uses `.glob` references, which are a coarse summary of
dependencies.  LF is smaller and more explicit:

- The core language has explicit terms, lambdas, Pi-types, and constants.
- There is no tactic language in the kernel; a Twelf signature is a collection
  of constants, type families, and constructors.
- The type theory is dependently typed, but the surface syntax is close to the
  core.
- `twelf-server` gives a simple yes/no oracle for a candidate slice.

This makes it easier to relate a declaration-level slicer to the paper's
type-directed slicing.  It does **not** make the prototype a full
type-directed slicer: the implementation still uses identifier occurrences,
not a typing derivation.

## LF mapping

| Paper / Rocq idea | Twelf/LF analogue |
|---|---|
| declaration | constant declaration |
| type family / inductive type | type family `a : K` |
| constructor / proof rule | constant `c : A` whose result head is `a` |
| theorem statement | type of a declaration |
| proof term | definition body / constructor term |
| exact slice | closure over types and bodies, plus logic-program constructors |
| proof skeleton | type-only closure, bodies dropped |
| compiler oracle | `twelf-server` `loadFile` |

## Algorithm

1. Strip Twelf comments while preserving `%mode`-style directives.
2. Split the signature into declarations at top-level periods.
3. Parse each declaration into a name, type, and optional body.
4. Extract identifiers from the type and body.  Remove bound variables from
   `{x:A}` and `[x:A]`; keep only identifiers that name declared constants.
5. Identify type families (`... -> type`) and constructors (result head `F`).
6. Record `%mode F ...` as a logic-program marker.
7. Compute one of two closures:
   - exact: follow type and body edges; for a `%mode` family, add all of its
     constructors; for a constructor of a `%mode` family, add its siblings.
   - statement: follow only type edges; do not add constructors.
8. Render the kept blocks in source order.  In statement mode, drop the body of
   a typed declaration.  Keep syntax directives (`%name`, `%infix`, `%prefix`,
   `%postfix`) whose dependencies are kept; drop proof/termination directives.
9. Optionally minimize by trying to remove each non-target block and checking
   the candidate with `twelf-server`.
10. Optionally export the graph as DOT or Mermaid.

## Exact vs statement

Exact mode is intended to preserve the logic program associated with a target:

```text
plus : nat -> nat -> nat -> type.
%mode plus +X +Y -Z.
p_z : plus z Y Y.
p_s : plus (s X) Y (s Z) <- plus X Y Z.
```

If `p_s` is the target, exact mode keeps `p_z` as well because `plus` is a
`%mode` family.  Without `p_z`, the remaining declarations still type-check,
but `plus` is no longer the same logic program.

Statement mode intentionally gives that up.  It keeps only what is needed to
state the target and drops bodies:

```text
plus : nat -> nat -> nat -> type.
p_s : plus (s X) Y (s Z) <- plus X Y Z.
```

This is useful for error localization and for inspecting the statement
dependency cone, but it is not a proof-preserving reduction.

## What is still missing?

- **Typing derivation.**  The slicer sees identifier occurrences, not the full
  LF typing derivation.  A stricter implementation would instrument Twelf's
  type checker or use a formalized LF checker.
- **Definitional equality.**  LF has beta/eta and transparent definitions.
  Removing a definition body can change conversion.  Statement mode is
  therefore a syntactic skeleton, not a semantics-preserving one.
- **Full Twelf surface syntax.**  `%theorem`, `%prove`, `%assert`, `%block`,
  `%abbrev`, and user-defined operators are only partially handled.
- **Semantic proof preservation.**  Exact mode preserves syntax-level
  dependencies and logic-program constructors, but it does not prove that the
  sliced signature has the same operational behavior.
- **Real proofs.**  The corpus is tiny and hand-written.  A realistic
  evaluation would use Twelf developments such as the examples shipped with
  Twelf or a larger metatheory.

## Comparison with the Rocq prototype

| | Rocq prototype | Twelf prototype |
|---|---|---|
| core | CIC | LF |
| dependency source | `.glob` + identifiers | identifier occurrences |
| tactics | common | absent from core |
| conversion | complex | simpler, but still present |
| exact slice | reachable proofs | type/body closure + mode constructors |
| skeleton | `Admitted` | bodies dropped |
| oracle | `rocq compile` | `twelf-server` |
| main gap | conversion-aware analysis | typing derivation and full syntax |

The Twelf prototype is closer to the paper in the sense that the object language
is small and terms are explicit.  It is still a dependency slicer rather than a
full type-directed slicer.
