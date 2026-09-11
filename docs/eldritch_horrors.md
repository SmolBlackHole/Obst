# Eldritch horrors

Parent: [Documentation index](README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

OBST allows entire formats to exist above it without understanding what they
mean. This page explores what applications can build from the existing
[container model](anatomy.md). These are composition patterns, not additional
wire features or a promise of finished applications. Working implementations
are linked; invented contract IDs are explicitly illustrative.

Read from the top to move from domain formats through representation choices,
reader capabilities and archival constructions to whole toolchains. Or choose
one construction below. Each keeps its application responsibilities explicit
and links to the mechanism you would use.

## Table of contents

- [Eldritch horrors](#eldritch-horrors)
	- [Table of contents](#table-of-contents)
	- [A format for building formats](#a-format-for-building-formats)
	- [Several unrelated worlds in one container](#several-unrelated-worlds-in-one-container)
	- [The decoder does not need the encoder's life story](#the-decoder-does-not-need-the-encoders-life-story)
	- [Shared representation models](#shared-representation-models)
	- [Repacking without changing the data](#repacking-without-changing-the-data)
	- [Capability tiers and different machines](#capability-tiers-and-different-machines)
	- [Data archaeology kits](#data-archaeology-kits)
	- [OBST containing OBST](#obst-containing-obst)
	- [Bounded network envelopes](#bounded-network-envelopes)
	- [Bring your own little ecosystem](#bring-your-own-little-ecosystem)

## A format for building formats

OBST is deliberately incomplete. An application can define a package format,
schema or archive model above its representation layer. The publisher owns
those rules, including the parts that turn out to be a bad idea.

Suppose somebody publishes **FROG Package Format 1.0**, with these illustrative
stream contracts:

| Stream | Profile | Meaning defined by FROG |
| ------ | ------- | ----------------------- |
| 0 | `org.frog/manifest@1` | Package manifest and relationships between streams |
| 1 | `org.frog/binary@1` | Executable payload |
| 2..n | `org.frog/resource@2` | Application resources |

FROG specifies required streams, optional resources, compatibility, installation
and any signature scheme. Its format version is an application convention,
which it could identify through its manifest profile and application-owned
bytes. It does not need a new OBST header field.

OBST sees streams, metadata, Recipes and chunks. It checks container structure
and completeness and, with the required Stage decoders, reconstructs and
verifies logical bytes. It does not even need to know that this is a package.
Whether the executable is trustworthy or safe to install belongs to FROG.

The same boundary supports other possible applications:

| Application | What its publisher adds above OBST |
| ----------- | ---------------------------------- |
| Firmware or software bundles | Device targeting, resources, signatures and installation rules |
| Application exports and game saves | Schemas, versions and relationships between application objects |
| Telemetry | Units, timestamps and measurement record layouts |
| Research datasets | Sample meaning, provenance and validation conventions |
| ML artifacts | Relationships between weights, configuration and supporting data |
| Backups and snapshots | Snapshot consistency, restore rules and any deduplication |
| Long-lived archives | Preservation policy, documentation and recovery material |

These applications reuse OBST's framing, chunking, representation metadata and
integrity machinery. They still have to implement their own semantics. The
[wire specification](format.md) does not grow a package record whenever somebody
invents another kind of package.

To define such a format, start with the [stream-profile boundary](toolchain/extension-api/profiles.md)
and [contract identity](design.md#recipes-and-contract-identity). A Python
[Archiver](toolchain/extension-api/archivers.md) can compose domain inputs and
containers; it does not add package semantics to the wire format.

## Several unrelated worlds in one container

Nothing requires streams to share a domain. An illustrative container could hold:

```text
stream 0 -> org.example/telemetry@2
stream 1 -> org.example/model-weights@4
stream 2 -> obst.file@1
stream 3 -> org.example/savegame@7
```

Only [`obst.file@1`](../plugins/defaults/docs/contracts/streams/file.md) in that
example is a shipped profile. Each stream can use different Recipes. The
application decides whether the streams have any relationship at all.
OBST remains blissfully uninvolved in whatever architectural decision led here.

Several generations of one format can coexist too: legacy data, migrated data,
the original source and validation material. The application defines which is
authoritative and how to compare them. OBST neither performs the migration nor
infers equivalence from similar profile names. The
[stream model](anatomy.md#streams-own-logical-identity) supplies the underlying
independent byte sequences.

## The decoder does not need the encoder's life story

A [Recipe](anatomy.md#recipes-describe-reversible-representation) declares
versioned Stages in encoding order. Decoding applies their inverses in reverse
order. Each chunk names its actual Recipe, so one stream can mix representations:

```text
chunk 0 -> identity (empty Recipe)
chunk 1 -> obst.delta8@1 -> obst.zlib@1
chunk 2 -> identity (empty Recipe)
```

An encoder may choose among declared Recipes using heuristics or measurements.
It must finalize the manifest before publishing payloads; discovering Recipes
through search may therefore require spooling. The
[manifest-first design](design.md#manifest-first-chunked-operation) sets that
boundary. Recipes are declarative pipelines, not a general-purpose VM.

The working [Adaptive-Zlib plugin](../examples/plugin_adaptive_zlib/README.md)
demonstrates another route: it tries byte layouts and dictionaries inside one
Stage and records the selected representation in that Stage's payload.
That differs from switching the chunk's outer Recipe. Either way, the decoder
reads the recorded choice without repeating the search or consulting the
alignment of the planets.

## Shared representation models

[Stage parameters](format.md#recipe-entries) are contract-owned bytes in the
manifest. Many chunks can reference one Recipe and reuse its parameter set.
This already has a concrete implementation:
[`obst.zlib@2`](../plugins/defaults/docs/contracts/stages/zlib-dictionary.md)
carries a preset dictionary in its Stage parameters.

Other publishers could define contracts for codebooks, lookup tables or
reversible predictor configurations. Each contract must specify how to recover
individual chunks. Sharing declared parameters does not introduce mutable
history between chunks, and the model still consumes manifest space and local
resource budget. Putting something enormous in metadata does not make it free.

## Repacking without changing the data

An application can recover verified logical bytes and write a new container
using different Recipes. Application meaning stays the same only if stream
profiles, metadata and relationships are preserved as well.

The encoded bytes and container commitment change. A signature over the old
container does not magically transfer. This follows from composing
[reading](toolchain/reading.md) and [writing](toolchain/writing.md); it is not
a claim of a shipped generic repacking command.

## Capability tiers and different machines

An application can offer separate streams for a preview, portable data and a
specialized representation. The preview might use an identity Recipe while
the other streams require additional decoders.

A client can structurally consume the whole container while
[decoding selected chunks](toolchain/reading.md#selective-chunk-decoding).
The application chooses a useful stream and defines its relationship to the
others. Skipped streams have not had their logical bytes verified. OBST does
not automatically negotiate a fallback or convert between tiers.

An embedded writer and a server can likewise implement different subsets of the
same versioned contracts. They do not need equal computing power or the same
implementation language. This is an architectural possibility, not evidence of
a shipped embedded port or measured memory usage; the
[project status](../README.md#status) keeps those limits explicit.

Unknown does not mean corrupt. Sometimes you can read the wrapping and only
part of what is inside it.

## Data archaeology kits

Ordinary logical streams can carry the material needed to understand other streams:

```text
actual-data
specification.pdf
decoder-source.tar
decoder.wasm
conformance-vectors.zip
README.md
```

An archive application can preserve data, contracts, implementations and tests
together. Future machines may still struggle to build or run the decoder, but
future humans have something more useful than a dead specification website.

Bootstrap material must use contracts the initial reader already supports.
Storing the only decoder behind the codec it decodes is an excellent way to
preserve a circular dependency.

Decoder artifacts remain data. OBST does not automatically execute them.
An application that extracts and runs one needs its own explicit trust and
isolation policy. The [plugin system](toolchain/plugins.md#trust-boundary)
does not supply a portable decoder sandbox.

The archive can even carry OBST's specification, reference implementation,
Extensions and conformance corpus. A minimal compatible reader could recover
the material needed to build a richer one. The fruit can contain instructions
for growing more fruit.

## OBST containing OBST

A logical stream is bytes. An OBST container is bytes. Therefore:

```text
OBST(OBST(OBST(...)))
```

The outer reader can recover the inner container without understanding it.
Verifying the outer representation does not validate the inner container;
an application must explicitly open and check that separately. The
[recursion boundary](design.md#recursion-is-composition) provides no automatic
traversal. May God have mercy on your stack.

## Bounded network envelopes

The [reader's input boundary](toolchain/reading.md#structural-reading) requires
binary reads, not a path or seeking. A caller can supply a socket wrapper,
HTTP body, pipe, database BLOB stream or object-store response.

An application can use OBST as an envelope for a finite transfer containing
metadata, payload and attachments. The manifest comes first, and the terminal
commit establishes completeness. EOF alone is not success; incremental output
remains provisional until the container completes.

The transport must delimit the container appropriately. Carrying OBST bytes
over a network supplies neither an HTTP integration nor an endless interactive
messaging protocol.

## Bring your own little ecosystem

A [third-party Python plugin](toolchain/plugins.md) can contribute:

```text
Stream profiles and Stages
Packagers and Carriers
CLI commands
Resource definitions and limit profiles
Portable conformance cases
```

A publisher can bring domain contracts, packaging policy and commands to the
generic host. Only stream-profile and Stage IDs enter the container; the other
capabilities are selected by the host. The Core needs no project-specific code.

[obst-defaults](../plugins/defaults/README.md) and
[Adaptive-Zlib](../examples/plugin_adaptive_zlib/README.md) exercise the public
contribution mechanism. There is no first-party VIP entrance. An application
still has to implement its domain rules; OBST has declined to make those
everybody else's problem.

Choose an [Extension boundary](toolchain/extensions.md) to implement one piece,
or return to the [reading paths](README.md#choose-a-starting-point) for a
complete route through the relevant guides.

**If you found a new eldritch horror, please open an issue.**
