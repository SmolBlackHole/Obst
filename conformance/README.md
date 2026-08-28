# OBST conformance vectors

Parent: [Conformance and interoperability](../docs/conformance.md)

This directory is the language-neutral interoperability corpus for OBST. It
separates exact reference encodings from containers that must be accepted or
rejected at a declared validation phase. The catalog describes structural
results, capability requirements, logical recovery and failure classifications
without naming Python classes or requiring the reference implementation.

## Table of contents

- [OBST conformance vectors](#obst-conformance-vectors)
	- [Table of contents](#table-of-contents)
	- [Vector categories](#vector-categories)
	- [Validation phases](#validation-phases)
	- [Layout](#layout)
	- [Catalog](#catalog)
	- [Using the vectors](#using-the-vectors)
	- [Negative-vector discipline](#negative-vector-discipline)
	- [Rebuilding and checking](#rebuilding-and-checking)

## Vector categories

| Category | Required result |
| --- | --- |
| `golden` | The reference writer reproduces the exact container bytes, and every conforming reader accepts them. |
| `valid` | Structural validation succeeds. Recovery either succeeds as declared or is unavailable because an explicitly named capability is absent. |
| `invalid` | The container is rejected at the cataloged structural or recovery phase under a language-neutral classification. |

The distinction matters for codecs such as zlib. Different conforming encoders
may produce different compressed bytes while every decoder still recovers the
same logical payload.

## Validation phases

Catalog schema 2 separates 2 questions that must not be collapsed:

```text
structural validation
    -> accept or reject framing, references and stored integrity
    -> when accepted, attempt logical recovery if requested
    -> recover, report a missing capability or reject decoded bytes
```

`expected.structural` is present for every vector. An accepted structure also
has `expected.recovery`, whose result is `success`, `unavailable` or `reject`.
This distinction keeps a valid container that uses an unavailable Stage from
being mislabeled as corrupt. Recovery rejection covers errors that can only be
observed after executing a known Stage, including logical-size and logical-hash
failures.

## Layout

```text
conformance/
    README.md
    index.json
    containers/
        0.1-apple/
            golden/
            valid/
            invalid/
```

Container vectors are ASCII hexadecimal. Whitespace is insignificant, so a
reader may remove it and decode each pair of hexadecimal digits as one byte.
The directory name carries the container-format identity; Stage and stream
contract versions remain independent identities inside each manifest.

## Catalog

[`index.json`](index.json) is the machine-readable source of expected results.
Every record contains:

- a stable vector ID and category;
- its path and SHA-256 over decoded container bytes;
- feature tags describing the exercised boundary; and
- the exact Extension IDs required for logical recovery;
- one structural acceptance or rejection result; and
- when structurally accepted, one recovery result with logical streams,
  missing capabilities or a rejection classification.

Logical stream expectations contain exact size, SHA-256 and hexadecimal bytes.
The corpus is deliberately small enough that independent implementations can
start without downloading the image samples.

## Using the vectors

A reader test performs the same basic operation in any language:

```text
read index.json
    -> decode the referenced hexadecimal container
    -> verify its SHA-256
    -> apply expected.structural
    -> when accepted, resolve required_extensions
    -> apply expected.recovery
```

The `unused-unknown-stage` case is valid. Its unknown Stage occurs only in an
unused Recipe, so the required logical payload remains decodable without that
provider. `required_extensions` therefore lists only capabilities used by
chunks that must be decoded. Invalid vectors list none because their expected
operation is structural rejection rather than logical recovery. Missing local
capability is not structural corruption.

The `used-unknown-stage` case is also structurally valid. Its recovery result is
`unavailable`, and the catalog names the missing Stage explicitly. An
implementation that happens to provide a private implementation under that ID
may attempt recovery, but the portable corpus cannot prescribe logical bytes
without a published Stage contract.

## Negative-vector discipline

Each invalid vector changes one contract boundary whenever possible. Checksums
and terminal commitments are repaired when they are not the intended failure,
so an earlier integrity error does not hide the rule under test.

Classifications are language-neutral:

- `invalid_structure`
- `corrupt`
- `truncated`
- `unsupported_version`
- `decode_failure` at the recovery phase

Implementations may expose different exception types or diagnostic text. They
must agree on acceptance, rejection and recovered logical bytes.

## Rebuilding and checking

The checked-in corpus is generated deterministically:

```console
python scripts/build_conformance.py
python -m pytest tests/test_conformance_vectors.py
```

The build command updates every vector and removes obsolete generated `.hex`
files. The test regenerates the catalog and every vector in memory, detects
missing or orphaned files, verifies every digest, checks every structural and
recovery outcome, and enforces fixed-record plus manifest-semantic coverage.
Add a new vector only through the generator with its catalog record, normative
rule and regression coverage.

The corpus is boundary-complete for the explicit v0.1 validity rules, not an
exhaustive enumeration of every possible byte string. Property tests, mutation
matrices and independent implementations remain complementary evidence.
