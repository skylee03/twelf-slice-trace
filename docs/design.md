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
type-directed slicing.  The optional `--trace` backend goes one step further
and instruments Twelf's type checker, so dependency edges are the constants
actually visited during type checking, not source-level identifier matches.

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

## Typing trace

The patch adds `src/global/slice-trace.{sig,sml}`, instruments three places,
and writes a TSV file when `TWELF_SLICE_TRACE` is set:

1. `TypeCheck.inferCon` records every `Const`, `Def`, `Skonst`, and foreign
   constant visited during inference.
2. `ReconConDec.condecToConDec` sets the current declaration and the phase
   (`type` or `body`) before calling `TypeCheck.check`.  Trace mode forces the
   double-check even when `Global.doubleCheck` is false.
3. `Twelf.loadFile` resets the trace before parsing and flushes it after the
   file is processed.

The trace is therefore a record of the type checker's observations, not a
source-level approximation.  It is still not a full derivation tree: it records
which constants were visited, not every typing-rule application.  For slicing,
that is the relevant part.

## Algorithm

1. Strip Twelf comments while preserving `%mode`-style directives.
2. Split the signature into declarations at top-level periods.
3. Parse each declaration into a name, type, and optional body.
4. Obtain dependency edges:
   - with `--trace`: run the patched server and take edges from
     `TypeCheck.inferCon`, split into type and body phases;
   - without `--trace`: extract identifiers from the type and body, remove
     bound variables from `{x:A}` and `[x:A]`, and keep only declared names.
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

- **Full derivation tree.**  The trace records constants visited by the type
  checker, not a complete derivation object or every rule application.  A
  stricter implementation could instrument the checker to build a full
  derivation and slice over typing rules directly.
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
| dependency source | `.glob` + identifiers | type-checker trace or identifiers |
| tactics | common | absent from core |
| conversion | complex | simpler, but still present |
| exact slice | reachable proofs | type/body closure + mode constructors |
| skeleton | `Admitted` | bodies dropped |
| oracle | `rocq compile` | `twelf-server` |
| main gap | conversion-aware analysis | full derivation object and full syntax |

The Twelf prototype is closer to the paper in the sense that the object language
is small and terms are explicit, and the trace backend takes dependencies from
the type checker.  It is still a dependency slicer rather than a full
rule-by-rule type-directed slicer.
