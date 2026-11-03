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
re-implementation of LF type checking.

## Quick start

Requirements:

- Python 3.10+
- Twelf with `twelf-server` on `PATH`, or `TWELF_SERVER` pointing at it.

Build Twelf with SML/NJ if necessary:

```bash
brew install smlnj
git clone https://github.com/standardml/twelf.git
cd twelf
make smlnj
export TWELF_SERVER="$PWD/bin/twelf-server"
```

Run the demo:

```bash
cd twelf-proof-slicer
TWELF_SERVER=/path/to/twelf-server ./run.sh
```

Slice a signature:

```bash
twelf-slice corpus/nat.elf p_s --mode exact
twelf-slice corpus/nat.elf p_s --mode statement
```

Install as a command:

```bash
python3 -m pip install -e .
twelf-slice --help
```

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

For each declaration, the slicer extracts identifiers from its type and body.
Only identifiers that name declared constants become graph edges.  Bound
variables in `{x:A}` and `[x:A]` are excluded.  This avoids the usual
false-positive where a local variable has the same name as a top-level constant;
see `corpus/false_positive.elf`.

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

The corpus contains eight small signatures.  The numbers below come from
`selftest.py` and count non-blank lines, excluding the generated header.

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

Mean reduction:

- exact: **49.2%** (range 30.8%–66.7%);
- statement: **71.5%** (range 61.5%–84.6%).

All sixteen slices pass `twelf-server`.  This is a sanity corpus, not a
benchmark.

## Tests

Unit tests do not need Twelf:

```bash
python3 -m unittest discover -s tests -v
```

Integration tests and the end-to-end self-test need `twelf-server`:

```bash
TWELF_SERVER=/path/to/twelf-server python3 -m unittest discover -s tests -v
TWELF_SERVER=/path/to/twelf-server python3 selftest.py
```

## Repository layout

```text
twelf-proof-slicer/
├── twelf_slicer/
│   ├── slicer.py        # parser, closures, rendering, Twelf oracle
│   └── cli.py           # twelf-slice entry point
├── corpus/              # eight small .elf signatures
├── tests/
│   ├── test_unit.py
│   └── test_integration.py
├── selftest.py          # end-to-end corpus check and statistics
├── run.sh               # one-command demo
├── docs/design.md       # design notes and limitations
└── pyproject.toml
```

## Limitations

- Dependencies are extracted from source-level identifier occurrences, not from
  a typing derivation.  This is closer to LF than `.glob`-based Rocq slicing,
  but it is still not the paper's full type-directed analysis.
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
