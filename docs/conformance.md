# Conformance and interoperability

Parent: [Documentation index](README.md)

Conformance checks whether an implementation follows the published OBST
contracts without depending on Python internals. This page owns the shared
conformance model, the format corpus and the evidence from documentation-only
readers. The [binary format](format.md) and versioned Extension contracts remain
normative.

## Table of contents

- [Conformance and interoperability](#conformance-and-interoperability)
	- [Table of contents](#table-of-contents)
	- [What conformance establishes](#what-conformance-establishes)
	- [Interoperability evidence](#interoperability-evidence)
		- [Current sample facts](#current-sample-facts)
		- [Specification feedback](#specification-feedback)
	- [Portable suites](#portable-suites)
		- [Format corpus](#format-corpus)
		- [Plugin extension suites](#plugin-extension-suites)
	- [What remains unproven](#what-remains-unproven)

## What conformance establishes

OBST uses several kinds of evidence because they answer different questions:

| Evidence                   | What it establishes                                                       |
| -------------------------- | ------------------------------------------------------------------------- |
| Normative specification    | The bytes and behavior an implementation must accept or reject.           |
| Portable conformance suite | Repeatable inputs and language-neutral expected outcomes.                 |
| Independent implementation | Whether the published contracts are sufficient without reference code.    |
| Distribution-owned tests   | Whether one concrete implementation follows its contracts and lifecycles. |

None replaces the others. Passing vectors does not make unclear prose
normative, and one successful clean-room reader does not cover every malformed
container or Extension input.

## Interoperability evidence

Three documentation-led exercises have tested the format boundary:

1. An external clean-room reader reconstructed a historical pre-freeze
   `samples/apple.obst`. It used the published format and Extension contracts,
   validated framing and logical integrity, inverted zlib, interpreted
   `obst.file@1` metadata and recovered the source image without the Python
   reference implementation. The historical container predates the terminal
   commit used by the current format.

2. A second independently reported reader received the published
   documentation, one source image, an older invalid container and the current
   `samples/all-fruit.obst`. It rejected the invalid draft, recovered 3
   `obst.file@1` streams from the valid container, recognized those bytes as
   nested OBST containers and recovered the images inside them.

3. A later near-clean-room check used only `docs/format.md`, Python's standard
   library and the raw bytes of the current `samples/apple.obst`. It parsed and
   validated that sample, then generated a 300-byte container with one
   `obst.bytes@1` stream and an illustrative `org.example/identity@1` Stage.
   The reference CLI accepted the generated container structurally and
   reported the missing local Stage exactly as expected. This was a constrained
   project-side check, not an independent implementation.

The first recovered payload was 370,221 bytes with SHA-256:

```text
5f1da67da16ad1a9a48cf97598826847d3c2420747d53f4ceb73b4ae0baa9492
```

That digest still matches the current source image. The historical container
was 266,791 bytes with SHA-256
`19e90108183e4dad2657c5331c6f37cdb3a5e96e181d721a83b375edcbff05cc`.

### Current sample facts

The checked-in `samples/apple.obst` exercises the current terminal commit:

| Property          | Value                           |
| ----------------- | ------------------------------- |
| Container size    | 266,889 bytes                   |
| Container SHA-256 | `7affd252...62b0aa11ea`         |
| Manifest size     | 310 bytes                       |
| Extensions        | 2: `obst.file@1`, `obst.zlib@1` |
| Recipes           | 1: `obst.zlib@1`                |
| Streams           | 1: `obst.file@1`                |
| Chunks            | 6                               |
| Logical size      | 370,221 bytes                   |
| Logical SHA-256   | `5f1da67d...4ae0baa9492`        |
| Source comparison | byte-identical                  |
| Terminal commit   | valid                           |

### Specification feedback

The independent readers recovered their samples without an
interoperability-blocking ambiguity, but the work exposed rules that had been
too easy to infer from the Python implementation:

- extension identifiers needed explicit separator and leading-zero rules;
- specification URLs needed an exact accepted syntax;
- `obst.file@1` needed an exact Unicode control-character rule; and
- Windows-reserved filenames needed an explicit case-comparison rule.

Those rules now live in the [binary format](format.md#extension-table) and the
plugin-owned [`obst.file@1` contract](../plugins/defaults/docs/contracts/streams/file.md#metadata),
where an independent implementation can find them.

## Portable suites

The public `obst.conformance` package represents portable cases as an immutable
`ConformanceSuite`. Catalog schema 2 stores one suite in a single `index.json`;
plugin packages conventionally place it under `conformance_vectors/`. The file
contains stable case IDs, canonical inline hexadecimal bytes, SHA-256 digests
and language-neutral outcomes.

The case kinds cover 4 boundaries:

| Boundary         | Cases                                                                   |
| ---------------- | ----------------------------------------------------------------------- |
| Container        | Structural acceptance or rejection and complete logical recovery.       |
| Stage bytes      | Known answers, decode rejection and encoder or decoder output ceilings. |
| Stage parameters | Canonical parameter interpretation and binding rejection.               |
| Stream metadata  | Canonical interpretation and rejected metadata.                         |

Catalogs contain data, not pytest modules, callbacks or Python exception
names. `load_conformance_suite()` validates package data,
`write_conformance_suite()` writes it deterministically and
`run_conformance_suite()` checks one suite against explicitly supplied
providers. Other languages can consume the same JSON without importing Python.

### Format corpus

The `obst` distribution ships 80 structural cases in the packaged
[format corpus](../src/obst/conformance/corpus/). They cover valid containers,
invalid structure, corruption, truncation, unsupported versions and missing
local Stage capabilities. The corpus imports no production Extension provider.

It is exposed as the `obst-format` conformance contribution through the same
plugin path used by other distributions:

```console
obst plugins test obst-format
```

The [format specification](format.md#conformance-vectors) owns the exact wire
coverage. The corpus file owns the exact bytes and expected results.

### Plugin extension suites

Each plugin owns the suite, generator, documentation and ordinary tests for
the contracts it implements. A suite that accompanies wire-visible Stage or
stream-profile providers must cover each of those providers. It may also
include complete-container recovery cases with explicit Extension
dependencies.

The [`obst-defaults` conformance guide](../plugins/defaults/docs/conformance.md)
documents its concrete cases and regeneration command. Runtime-only Carriers
and Packagers have no wire vectors; their request, lifecycle and publication
behavior belongs in that distribution's ordinary tests.

Publishing and selecting an `obst.conformance` entry point is documented in the
[plugin guide](extensions/plugins.md#conformance-contribution). Reading the
static JSON does not execute plugin code. Loading its factory or running cases
against its providers does, so conformance execution is not a sandbox.

## What remains unproven

The external clean-room implementations and their reusable run logs are not
checked into this repository. The historical container is also absent. Their
results are interoperability evidence, not reproducible project tests. The
near-clean-room script and generated container were temporary artifacts and do
not improve that independence claim.

The generated corpus is reproducible, but it is still generated and exercised
by the reference project. Preserved cross-language execution against the full
corpus remains open in the
[current stabilization milestone](../ROADMAP.md#now-pre-public-stabilization).
The same milestone owns the unresolved question raised by the near-clean-room
writer: whether a zero-Stage Recipe should become the canonical identity
representation.
