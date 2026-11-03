# Twelf/LF Proof Slicer

A small, dependency-directed slicer for [Twelf](https://twelf.org/) / LF
signatures.  Given a Twelf signature and a target declaration, it renders a
smaller signature and uses `twelf-server` as the final type-checking oracle.

This is the LF counterpart of the Rocq prototype in `../rocq-proof-slicer`.
Twelf is interesting for this experiment because LF has:

- explicit terms, with no tactic language in the core;
- a small dependently typed theory;
- explicit type families and constructors;
- a source-level checker that is easy to use as an oracle.

The prototype is intentionally **declaration-level**.  It is not a full
re-implementation of LF type checking.  It has two dependency backends:

- a source-level fallback that matches identifiers in types and bodies;
- an optional **typing trace** produced by an instrumented `twelf-server`,
  which records the constants actually visited by the LF type checker.

## Quick start

Requirements:

- Python 3.10+
- Twelf with `twelf-server` on `PATH`, or `TWELF_SERVER` pointing at it.
- For `--trace`: the patched Twelf server from `patches/`.

Build the patched server with SML/NJ:

```bash
brew install smlnj
cd twelf-proof-slicer
./scripts/build-twelf-trace.sh
export TWELF_SERVER="$PWD/.twelf-src/bin/twelf-server"
```

The script clones Twelf at the commit recorded in the patch, applies
`patches/twelf-slice-trace.patch`, and runs `make smlnj`.

Run the demo:

```bash
TWELF_SERVER=/path/to/twelf-server ./run.sh
```

Slice a signature using the source fallback:

```bash
twelf-slice corpus/nat.elf p_s --mode exact
twelf-slice corpus/nat.elf p_s --mode statement
```

Slice using the type-checker trace:

```bash
twelf-slice corpus/nat.elf p_s --mode exact --trace
```

Install as a command:

```bash
python3 -m pip install -e .
twelf-slice --help
```

## Typing trace (`--trace`)

The stock Twelf API exposes the checker's yes/no result, but not the constants
that the checker visits.  `patches/twelf-slice-trace.patch` adds a small
`SliceTrace` structure and instruments:

- `TypeCheck.inferCon`: every `Const` / `Def` visited during inference is
  recorded;
- `ReconConDec`: the current declaration and phase (`type` or `body`) are set
  around the checker calls;
- `Twelf.loadFile`: the trace is reset and flushed at file boundaries.

When `TWELF_SLICE_TRACE` is set, the patched server writes a TSV file:

```text
decl    p_s     object
type    p_s     plus
type    p_s     s
type    p_s     nat
```

The Python client runs the server with a temporary trace path and replaces the
source-level edges with these type-checker edges.  The trace is not a full
derivation tree; it is the set of constants observed during the checking run,
split into type and body phases.  That is enough for dependency slicing, and it
is strictly more faithful than identifier matching.

A concrete difference: for `p_s` the source only mentions `plus` and `s`; the
type checker also infers `nat` for the implicit variables `X`, `Y`, `Z`.  The
trace records that edge.

There is also a scope-capture regression in `corpus/scope_capture.elf`: the
source fallback drops both occurrences of `helper`, while the trace keeps the
free one.  The exact source slice fails to check; the traced slice succeeds.

## Modes

### `exact`

Follows both type references and definition-body references from the target.
When a kept type family has a `%mode` declaration, all of its constructors are
kept as well; this preserves the logic program associated with the family.
Directives whose dependencies are all kept are preserved.

For `corpus/nat.elf` and target `p_s`, this keeps:

```text
nat, z, s, plus, p_z, p_s
%mode, %worlds, %total
```

It drops the unrelated `even` family.

### `statement` (alias: `skeleton`)

Follows only the type-level dependencies of the target.  Definition and proof
bodies are rendered without their right-hand side, so a declaration

```text
target : lt z (s z) = lt_s le_z.
```

becomes

```text
target : lt z (s z).
```

This is the LF analogue of replacing a proof body with `Admitted`.  It is a
*syntactic* skeleton: `twelf-server` checks that the result is well typed, but
the result is not claimed to have the same proof-theoretic meaning as the
original.

### `--minimize`

Greedily removes declarations and directives while `twelf-server` still accepts
the result.  This is **typecheck-minimal**, not proof-semantics-minimal: it may
remove constructors that are needed by a logic program even though the remaining
signature still type-checks.

```bash
twelf-slice corpus/nat.elf p_s --mode exact --minimize
```

## What counts as a dependency?

With `--trace`, dependencies are the constants visited by the type checker
(`TypeCheck.inferCon`), split into type and body phases.  Without `--trace`, the
slicer falls back to source-level identifier extraction: identifiers from the
type and body are kept only when they name declared constants; bound variables
in `{x:A}` and `[x:A]` are removed.

The LF-specific part is the treatment of type families:

- a declaration whose type is a kind (`... -> type`) is a type family;
- a declaration whose result type has head `F` is a constructor of `F`;
- a `%mode F ...` declaration marks `F` as a logic program, so an exact slice
  keeps all constructors of `F`.

## Example output

```console
$ twelf-slice corpus/list.elf append_cons --mode statement
%% Sliced from list.elf for target append_cons (statement)

nat : type.

list : type.

nil : list.

cons : nat -> list -> list.

append : list -> list -> list -> type.

append_cons : append (cons X L1) L2 (cons X L3) <- append L1 L2 L3.

twelf-slice: target=append_cons mode=statement decls=5 lines=17->6 (-64.7%)
twelf-slice: Twelf check OK
```

## Evaluation corpus

The corpus contains nine small signatures.  The eight baseline cases work with
either backend; `scope_capture.elf` is a trace-only regression.  The numbers
below come from `selftest.py` and count non-blank lines, excluding the generated
header.

| file | target | exact | statement |
|---|---|---:|---:|
| `nat.elf` | `p_s` | 13 → 9 (30.8%) | 13 → 4 (69.2%) |
| `list.elf` | `append_cons` | 17 → 10 (41.2%) | 17 → 5 (70.6%) |
| `bool.elf` | `not_t` | 20 → 9 (55.0%) | 20 → 5 (75.0%) |
| `definitions.elf` | `two` | 13 → 5 (61.5%) | 13 → 2 (84.6%) |
| `infix.elf` | `impe` | 15 → 5 (66.7%) | 15 → 5 (66.7%) |
| `false_positive.elf` | `target` | 9 → 3 (66.7%) | 9 → 2 (77.8%) |
| `chain.elf` | `target` | 13 → 8 (38.5%) | 13 → 5 (61.5%) |
| `judgment.elf` | `of_app` | 15 → 10 (33.3%) | 15 → 5 (66.7%) |
| `scope_capture.elf` (trace) | `target` | 10 → 6 (40.0%) | 10 → 2 (80.0%) |

Mean reduction with the typing trace:

- exact: **48.2%** (range 30.8%–66.7%);
- statement: **72.5%** (range 61.5%–84.6%).

All eighteen traced slices pass `twelf-server`.  On `scope_capture.elf`, the
source fallback's exact slice fails because it drops the free `helper`; the
traced slice succeeds.  This is a sanity corpus, not a benchmark.

## Tests

Unit tests do not need Twelf:

```bash
python3 -m unittest discover -s tests -v
```

Integration tests and the end-to-end self-test need `twelf-server`:

```bash
TWELF_SERVER=/path/to/twelf-server python3 -m unittest discover -s tests -v
TWELF_SERVER=/path/to/twelf-server python3 selftest.py
TWELF_SERVER=/path/to/twelf-server python3 selftest.py --trace
```

The trace tests require the patched server; unpatched servers are skipped where
possible.

## Repository layout

```text
twelf-proof-slicer/
├── twelf_slicer/
│   ├── slicer.py        # parser, closures, rendering, Twelf oracle
│   ├── trace.py         # patched-server trace client
│   └── cli.py           # twelf-slice entry point
├── patches/
│   └── twelf-slice-trace.patch
├── scripts/
│   └── build-twelf-trace.sh
├── corpus/              # nine small .elf signatures
├── tests/
│   ├── test_unit.py
│   └── test_integration.py
├── selftest.py          # end-to-end corpus check and statistics
├── run.sh               # one-command demo
├── docs/design.md       # design notes and limitations
└── pyproject.toml
```

## Limitations

- `--trace` dependencies come from the constants visited by Twelf's type
  checker, split into type and body phases.  This is not a full derivation tree:
  it records observed constants, not every rule application or a proof object.
  Without `--trace`, dependencies are source-level identifier occurrences.
- The patched Twelf server is required for trace mode.  The patch is tied to a
  tested Twelf commit and may need rebasing for newer Twelf versions.
- The parser covers the constructor/definition/directive fragment used by the
  corpus.  It does not implement the full Twelf grammar, `%theorem`/`%prove`
  blocks, modules, or all operator forms.
- Twelf definitions are expanded during checking.  The statement slice makes
  definitions opaque, which can change definitional equality.  If that matters,
  use exact mode or keep the relevant bodies.
- Exact mode preserves all constructors of a `%mode` family.  This is a
  heuristic for preserving the logic program, not a semantic proof.
- `--minimize` is only a type-checking oracle loop; it can remove proof rules
  that are semantically necessary.
- The prototype does not attempt tactic-level slicing.  LF has no tactic
  language in the core, so that problem simply does not arise here.

## Design notes

See [docs/design.md](docs/design.md) for the LF mapping, closure algorithm, and
a comparison with the Rocq prototype.
