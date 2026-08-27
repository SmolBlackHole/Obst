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
	- [Python extension test kit](#python-extension-test-kit)
	- [Coverage boundary](#coverage-boundary)
	- [Specification feedback](#specification-feedback)
	- [Evidence status](#evidence-status)

## First clean-room result

An external clean-room reader reconstructed the `samples/apple.obst` revision
stored in Git commit `f442ebc`. That pre-freeze draft ended after its last chunk
and did not yet contain the terminal commit that now proves stream completeness.
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
containers that every reader must reject.

The machine-readable catalog records vector digests, covered features, exact
Extension IDs required for logical recovery, exact logical outputs and
language-neutral rejection classifications. Its own [`README`](../conformance/README.md)
is the authoritative vector catalog.

## Reference conformance coverage

The `obst-defaults` plugin separately publishes portable cases for its
first-party Stage contracts without requiring encoder byte identity. Its own
test suite exercises all declared zlib compression levels, dictionary-free and
preset-dictionary round trips, output limits and rejection of truncated,
trailing or concatenated RFC 1950 streams. Delta8 has fixed known-answer cases
and proves that its previous-byte state resets at each chunk boundary.

The decode-only Delta8 plus zlib vector fixes one valid multi-chunk
representation, not the output of every conforming zlib encoder.

These tests establish the reference provider's behavior. They do not replace
running the public vectors in another language or preserving an independent
implementation and its execution evidence.

## Python extension test kit

Third-party Stage packages can use the pytest-independent
`obst.conformance.check_stage_conformance()` helper in their own test suite. A
`StageConformanceCase` checks a known encoded representation, a locally produced
round trip and, only when the Stage contract requires it, exact canonical
encoding.

Extension authors may run the helper directly in their own repository or CI.
Installed plugins may publish the same cases explicitly; the
[plugin guide](extensions/plugins.md#run-published-conformance-cases) owns
loading, isolation from the enabled set and trusted-code semantics.

## Coverage boundary

Two successful samples do not establish complete conformance. The independent
runs do not cover interleaved streams, multiple Recipes, per-chunk Recipe
changes, RAW, Delta8, unknown extensions, empty streams or empty chunks. Those
boundaries have reference-side public vectors, but still need preserved
cross-language execution evidence.

The checked-in clean-room evidence also contains no preserved parser source or
run log. Preserving one independent implementation and its execution evidence
remains tracked under the [roadmap's conformance gaps](../ROADMAP.md#conformance-gaps).

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

The historical container remains recoverable from Git commit `f442ebc`; the
source image and current reference-side sample are checked into this repository.
The independence claims and clean-room reader behavior are external reports
supplied by the project author; neither separate reader is a repository
artifact. The results are meaningful interoperability evidence, while the
checked-in vector corpus is the reproducible suite for the current draft.
