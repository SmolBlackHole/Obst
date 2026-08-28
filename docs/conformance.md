# Conformance and interoperability

Parent: [Documentation index](README.md)

This page records whether the published OBST contracts are sufficient for an
implementation that does not depend on the Python reference code. It owns
interoperability evidence and its limits, while the binary and extension
contracts remain normative. The [container anatomy](anatomy.md) defines the
pieces exercised by the evidence.

## Table of contents

- [Conformance and interoperability](#conformance-and-interoperability)
	- [Table of contents](#table-of-contents)
	- [First clean-room result](#first-clean-room-result)
	- [Second clean-room result](#second-clean-room-result)
	- [Current sample facts](#current-sample-facts)
	- [What the results prove](#what-the-results-prove)
	- [Portable vector corpus](#portable-vector-corpus)
	- [Reference conformance coverage](#reference-conformance-coverage)
	- [Plugin extension suites](#plugin-extension-suites)
	- [Coverage boundary](#coverage-boundary)
	- [Specification feedback](#specification-feedback)
	- [Evidence status](#evidence-status)

## First clean-room result

An external clean-room reader reconstructed a historical pre-freeze revision of
`samples/apple.obst`. That draft ended after its last chunk and did not yet
contain the terminal commit that now proves stream completeness.
The reader used the published [binary format](format.md) and versioned
[contracts](README.md#normative-contracts), not the Python reference
implementation. It independently performed structural parsing, CRC and
logical-hash validation, zlib inversion, file metadata validation and stream
reconstruction.

Its reconstructed payload was 370,221 bytes with SHA-256:

```text
5f1da67da16ad1a9a48cf97598826847d3c2420747d53f4ceb73b4ae0baa9492
```

That digest is byte-identical to the source image, which has not changed.
The historical container itself was 266,791 bytes with SHA-256
`19e90108183e4dad2657c5331c6f37cdb3a5e96e181d721a83b375edcbff05cc`.

## Second clean-room result

A second independently reported reader used the published documentation, one
source image, an older invalid container and the current
`samples/all-fruit.obst`. It was not told that the valid container held other
OBST containers. The implementation validated the outer representation,
recovered its 3 `obst.file@1` streams, recognized those logical bytes as nested
containers and recovered the original images from them.

This exercises the current terminal commit, multiple streams, the file profile,
zlib decoding and explicit nested composition. The supplied invalid historical
container was rejected instead of being treated as a second format variant.
The independent implementation and a reusable run log are not checked into the
repository, so this remains author-reported interoperability evidence rather
than a reproducible test artifact.

## Current sample facts

The checked-in `samples/apple.obst` now exercises the terminal commit contract.
Local reference-side verification reports:

| Property          | Value                           |
| ----------------- | ------------------------------- |
| Container size    | 266,855 bytes                   |
| Container SHA-256 | `500eea9f...7b51f5aa3`          |
| Manifest size     | 276 bytes                       |
| Extensions        | 2: `obst.file@1`, `obst.zlib@1` |
| Recipes           | 1: `obst.zlib@1`                |
| Streams           | 1: `obst.file@1`                |
| Chunks            | 6                               |
| Logical size      | 370,221 bytes                   |
| Logical SHA-256   | `5f1da67d...4ae0baa9492`        |
| Source comparison | byte-identical                  |
| Terminal commit   | valid                           |

The six logical and encoded payload sizes are:

```text
65536 / 39421
65536 / 49811
65536 / 64589
65536 / 43800
65536 / 26327
42541 / 42151
```

## What the results prove

The clean-room result demonstrates that an independent implementer could use
the published pre-terminal v0.1 draft to validate and recover one real,
nontrivial OBST container. That sample exercised a complete manifest, extension
references, a file profile, a parameterized zlib stage, six chunks, framing
CRCs, payload CRCs, declared logical sizes and BLAKE2s-128 logical hashes.

Together, the reports show that independent readers recovered both a historical
single-stream draft and the current nested multi-stream representation without
using Python implementation details. This is evidence that OBST is an
implementation-independent byte format, not serialized Python architecture.

## Portable vector corpus

The public [`conformance/`](../conformance/) corpus turns format behavior into
small reusable artifacts. It contains exact Golden Vectors, valid containers
whose stored representation need not be reproduced and isolated invalid
containers rejected at a declared validation phase.

The machine-readable catalog records vector digests, covered features, exact
Extension IDs required for logical recovery, structural outcomes, capability
availability, exact logical outputs and language-neutral rejection
classifications. Structural acceptance is distinct from recovery, so a missing
decoder remains a local capability result rather than container corruption. Its
own [`README`](../conformance/README.md) is the authoritative vector catalog.

## Reference conformance coverage

The `obst-defaults` plugin separately ships a static portable suite for its
first-party Stage and stream-profile contracts. It covers known logical and
encoded Stage bytes, canonical parameter bytes, malformed parameters and
payloads, output limits, portable file metadata and rejected filenames. Its
ordinary test suite adds provider-specific coverage such as all declared zlib
compression levels, concurrent calls and filesystem publication behavior.

The decode-only Delta8 plus zlib vector fixes one valid multi-chunk
representation, not the output of every conforming zlib encoder.

These tests establish the reference provider's behavior. They do not replace
running the public vectors in another language or preserving an independent
implementation and its execution evidence.

## Plugin extension suites

Every Python plugin that publishes `obst.extensions` also publishes one
matching `obst.conformance` contribution. The plugin distribution owns a
static `ConformanceSuite` stored as package resources:

```text
conformance_vectors/
    index.json
    vectors/*.hex
```

Catalog schema `1` records stable case IDs, closed case kinds, Extension IDs,
SHA-256 digests and expected language-neutral behavior. The generic loader
rejects unknown fields, invalid identities, unsafe paths, missing artifacts or
wrong digests before running a case. The suite may cover:

- known Stage encodings and optional canonical encoder output;
- canonical Stage parameters and their inspection interpretation;
- rejected Stage parameters or payloads;
- encoder and decoder output ceilings;
- canonical or rejected stream metadata; and
- recovery of expected logical streams from one complete container.

The portable suite contains data, not pytest modules, callbacks or Python
exception names. Loading its entry-point factory and exercising its providers
still executes trusted plugin code. The [plugin guide](extensions/plugins.md)
owns publication, explicit dependency selection and that trust boundary.

`obst.conformance.load_conformance_suite()` loads a packaged suite and
`write_conformance_suite()` writes it deterministically. First-party artifacts
are regenerated with:

```console
python scripts/build_plugin_conformance.py
```

The narrow `check_stage_conformance()` helper remains available for directly
testing one `StageKnownAnswerCase` without plugin discovery. Runtime-only
carriers and packagers have no portable wire vectors because their request and
publication values are provider-specific; their lifecycle belongs in the
plugin's ordinary tests.

## Coverage boundary

Two successful samples do not establish complete conformance. The independent
runs do not cover most malformed fixed records, manifest invariants,
interleaved streams, per-chunk Recipe changes, RAW, Delta8, unknown extensions,
empty streams or empty chunks. Those boundaries now have generated
reference-side public vectors, but still need preserved cross-language
execution evidence.

The checked-in clean-room evidence also contains no preserved parser source or
run log. Preserving one independent implementation and its execution evidence
remains part of the
[current stabilization milestone](../ROADMAP.md#now-pre-public-stabilization).

## Specification feedback

The independent implementation recovered the sample without an
interoperability-blocking ambiguity, but it had to choose interpretations in
four contract areas:

1. separator and leading-zero rules in extension identifiers;
2. the exact syntax accepted for absolute ASCII specification URLs;
3. the Unicode category meant by a file-profile control character; and
4. case comparison for Windows-reserved file names.

The [binary format](format.md#extension-table) and
[`obst.file@1` contract](contracts/streams/file.md#metadata) now state those
rules directly instead of relying on the Python implementation to settle them.

## Evidence status

The historical container is not part of the public repository; its exact digest
is recorded above. The source image and current reference-side sample are
checked in. The independence claims and clean-room reader behavior are external
reports supplied by the project author; neither separate reader is a repository
artifact. The results are meaningful interoperability evidence, while the
checked-in vector corpus is the reproducible suite for the current draft.
