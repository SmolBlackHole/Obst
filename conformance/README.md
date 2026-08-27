# OBST conformance vectors

Parent: [Conformance and interoperability](../docs/conformance.md)

This directory is the language-neutral interoperability corpus for OBST. It
separates exact reference encodings from containers that every reader must
accept and containers that every reader must reject. The catalog describes
expected logical bytes and failure classifications without naming Python
classes or requiring the reference implementation.

## Table of contents

- [OBST conformance vectors](#obst-conformance-vectors)
	- [Table of contents](#table-of-contents)
	- [Vector categories](#vector-categories)
	- [Layout](#layout)
	- [Catalog](#catalog)
	- [Using the vectors](#using-the-vectors)
	- [Negative-vector discipline](#negative-vector-discipline)
	- [Rebuilding and checking](#rebuilding-and-checking)

## Vector categories

| Category | Required result |
| --- | --- |
| `golden` | The reference writer reproduces the exact container bytes, and every conforming reader accepts them. |
| `valid` | Every conforming reader accepts the container and recovers the declared logical bytes. Encoders need not reproduce the same representation. |
| `invalid` | Every conforming reader rejects the container under the cataloged language-neutral failure classification. |

The distinction matters for codecs such as zlib. Different conforming encoders
may produce different compressed bytes while every decoder still recovers the
same logical payload.

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
- the exact Extension IDs required for logical recovery; and
- either expected logical streams or one rejection classification and
  normative rule link.

Logical stream expectations contain exact size, SHA-256 and hexadecimal bytes.
The corpus is deliberately small enough that independent implementations can
start without downloading the image samples.

## Using the vectors

A reader test performs the same basic operation in any language:

```text
read index.json
    -> decode the referenced hexadecimal container
    -> verify its SHA-256
    -> parse and validate the complete container
    -> accept and compare logical streams, or reject as declared
```

The `unused-unknown-stage` case is valid. Its unknown Stage occurs only in an
unused Recipe, so the required logical payload remains decodable without that
provider. `required_extensions` therefore lists only capabilities used by
chunks that must be decoded. Invalid vectors list none because their expected
operation is structural rejection rather than logical recovery. Missing local
capability is not structural corruption.

## Negative-vector discipline

Each invalid vector changes one contract boundary whenever possible. Checksums
and terminal commitments are repaired when they are not the intended failure,
so an earlier integrity error does not hide the rule under test.

Classifications are language-neutral:

- `invalid_structure`
- `corrupt`
- `truncated`
- `unsupported_version`

Implementations may expose different exception types or diagnostic text. They
must agree on acceptance, rejection and recovered logical bytes.

## Rebuilding and checking

The checked-in corpus is generated deterministically:

```console
python scripts/build_conformance.py
python -m pytest tests/test_conformance_vectors.py
```

The test regenerates the catalog and every vector in memory, detects missing or
orphaned hexadecimal files, verifies every digest, decodes all valid cases and
checks every negative classification. Add a new vector only with its catalog
record, normative rule and regression coverage.
