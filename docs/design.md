# OBST design notes

Parent: [Documentation index](README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: CC-BY-ND-4.0
-->

This page explains why the implemented architecture has its boundaries. Exact
bytes live in the [binary format](format.md), Python behavior in the
[toolchain guide](toolchain/README.md), and unfinished work in the
[roadmap](../ROADMAP.md).

The central rule is simple: applications own meaning, OBST owns reversible
representation and framing, and callers own storage or transport. The
[container anatomy](anatomy.md) introduces the pieces connected by that rule.

## Table of contents

- [OBST design notes](#obst-design-notes)
	- [Table of contents](#table-of-contents)
	- [Ownership follows the bytes](#ownership-follows-the-bytes)
	- [Wire-visible and runtime extension points](#wire-visible-and-runtime-extension-points)
	- [Manifest-first, chunked operation](#manifest-first-chunked-operation)
	- [Stream semantics are not container semantics](#stream-semantics-are-not-container-semantics)
	- [Recipes and contract identity](#recipes-and-contract-identity)
	- [The encoder may be clever](#the-encoder-may-be-clever)
	- [Structure discovery through transforms](#structure-discovery-through-transforms)
	- [Numeric representation and scale](#numeric-representation-and-scale)
	- [Recursion is composition](#recursion-is-composition)
	- [Design goals and non-goals](#design-goals-and-non-goals)

## Ownership follows the bytes

OBST sits between logical bytes and their stored or transported form:

```mermaid
flowchart LR
    App["Application values"] --> Adapter["Profile or adapter"]
    Adapter -->|logical bytes| Recipe["Reversible Recipe"]
    Recipe --> Container["OBST framing and integrity"]
    Container -->|OBST bytes| Carrier["Caller-selected Carrier"]
    Carrier --> Storage["Storage or transport"]
```

The application or stream profile owns units, filenames, schemas and record
layouts. A Stage owns one reversible byte contract. OBST owns framing,
versioned contract references and integrity. The caller owns endpoints,
credentials and publication policy.

Reading follows the arrows in reverse without changing that ownership. A
filename does not become a core stream model, an S3 key does not enter the
manifest, and a specification URL does not grant permission to fetch code.

## Wire-visible and runtime extension points

Only identities required to understand container bytes enter the manifest:

| Extension point                 | Owns                                     | Wire-visible identity      |
| ------------------------------- | ---------------------------------------- | -------------------------- |
| Pipeline Stage                  | Reversible byte representation           | Versioned Stage ID         |
| Stream profile                  | Logical byte meaning and metadata        | Versioned stream type      |
| Packager policy                 | Recipes, chunking and tuning choices     | None                       |
| Carrier                         | Container input, output and publication  | None                       |
| Archiver or application adapter | Mapping domain inputs to logical streams | Only selected stream types |

Codecs and transforms are descriptions of a Stage, not separate core APIs. A
decoder needs the chosen Stage and stream contracts. It does not need to know
which Packager selected them, which adapter supplied the logical bytes or
which Carrier moved the completed container.

## Manifest-first, chunked operation

The manifest declares Extension IDs, Recipes and streams before the first
payload chunk. A reader can validate those declarations before payload bytes
arrive; complete inspection later distinguishes declared Stages from those
actually used by chunks. A writer must know the final manifest before
publishing payload bytes, and the low-level API does not hide buffering or
policy behind that constraint.

Independent chunk framing allows one non-seekable pass, bounded resource
checks, per-stream sequencing, stream interleaving and localized integrity
failures. The terminal commit marks successful completion and binds all
preceding records. EOF at a clean chunk boundary is still truncation.

A Packager that discovers Recipes by trying candidates needs bounded spooling
before it can finalize the manifest. Production tuning and spool policy remain
tracked in the [roadmap](../ROADMAP.md#later-production-encoding).

## Stream semantics are not container semantics

A stream is logical bytes plus a versioned stream-type ID and opaque metadata.
A decoder can recover the bytes without knowing whether they represent a file,
table or temperature series. Understanding that meaning is a separate profile
contract.

`obst.bytes@1` is the generic no-metadata contract. Publishers can define richer
profiles without teaching the core their domain model. The independently owned
[`obst.file@1` contract](../plugins/defaults/docs/contracts/streams/file.md) is
one example.

Metadata interpreters can improve inspection output. They do not change
structural validity or turn the core into a semantic decoder. The
[format validity flow](format.md#validity-availability-and-recovery) owns the
distinction between structure, decoder availability and recovery.

## Recipes and contract identity

A Recipe lists versioned Stages in encoding order. Decoding applies their
inverse operations in reverse order:

```text
logical bytes -> transform -> codec -> encoded bytes
logical bytes <- inverse   <- decode <- encoded bytes
```

An Extension ID names a language-neutral contract, not an implementation class
or package. That contract owns parameter bytes, representation, inverse
behavior, invalid inputs and resource rules. Incompatible behavior receives a
new ID version.

Finding a decoder permits an attempt; it does not prove the provider correct.
OBST verifies recovered chunks against their declared logical size and hash.
Provider-owned conformance suites test the broader contract claim.

## The encoder may be clever

The decoder executes the Recipe stored with a chunk. It does not need the
search history or the policy that selected it.

An encoder may use one fixed Recipe, a heuristic or a bounded candidate search.
It may optimize size, memory, encode time, decode time or flash usage. Every
candidate still needs an exact round trip, resource bounds and deterministic
selection. The identity Recipe remains correct when no transformation earns
its cost.

```text
identity Recipe | codec | transform -> codec
                         |
                         v
                   verify and score
                         |
                         v
                 selected Recipe bytes
```

Rejected candidates are diagnostics, not container data. Cleverness may also
live inside one Stage when its selected representation is fully described by
that Stage's parameters.

## Structure discovery through transforms

A general codec sees only patterns exposed by the byte layout. A reversible
transform can reveal structure without claiming to understand it.

Fixed-width records may begin as:

```text
ABCDEFGHIJKLMNOPQRSTUVWX
ABCDEFGHIJKLMNOPQRSTUVWX
ABCDEFGHIJKLMNOPQRSTUVWX
```

A width-24 shuffle could group equal columns:

```text
AAA...
BBB...
CCC...
...
XXX...
```

The transform becomes interoperable only when a versioned contract defines its
parameters, inverse, alignment behavior, invalid inputs and limits.

## Numeric representation and scale

Pipeline correctness means byte identity:

```text
decode(encode(input_bytes)) == input_bytes
```

Numeric equality is weaker. Signed zero and NaN payloads can have distinct bit
patterns, and arbitrary floats do not round-trip through a scaled integer.

Scaling therefore belongs to a versioned stream encoding. Its contract must
define integer width, byte order, decimal exponent, rounding, alignment and
rejected values. A deliberately lossy profile may quantize; that loss belongs
to the application format, never to a Stage advertised as reversible.

## Recursion is composition

An OBST container is bytes, so a logical stream may contain another complete
OBST container:

```text
OBST(OBST(OBST(...)))
```

The outer reader treats the inner container like any other payload. It does not
recurse because a filename ends in `.obst` or because recovered bytes begin
with OBST magic. Nested tooling needs explicit selection and resource limits;
that work remains in the [roadmap](../ROADMAP.md#later-directions).

The same boundary applies to application adapters. A profile owns semantic
metadata and materialization while the caller separately selects packaging and
storage.

## Design goals and non-goals

OBST aims to be:

- open and independently implementable;
- self-describing at the container and Recipe level;
- streamable with bounded-memory readers;
- inspectable when local decoders are missing;
- explicit about integrity and corruption;
- extensible through stable, versioned identities;
- byte-exact at the container and Recipe boundary; and
- small enough for a constrained C or C++ decoder.

OBST does not replace specialized semantic formats. PNG understands images,
Parquet understands columnar analytics and video codecs understand video. OBST
provides generic framing and reversible representation where that is useful.
