# OBST Roadmap

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

This file records the next meaningful OBST milestones. It is direction, not a
completion ledger, public defect register or detailed implementation plan.

Present behavior belongs to the [documentation index](docs/README.md), the
[binary format](docs/format.md), the [Extension guides](docs/toolchain/extensions.md)
and the [design notes](docs/design.md). Detailed audits remain private working
material. An approved plan may stay visible while its breaking change is in
flight. Completed work disappears from this page once its implementation,
tests and authoritative documentation agree.

## Now: compatibility groundwork

The current `0.2-apple` implementation reads, writes, inspects, packages and
extracts bounded OBST containers through explicitly activated extensions. The
remaining work before the first compatibility promise is to reproduce those
boundaries outside the reference implementation:

- preserve one independent reader implementation and run log against the
  public conformance corpus;
- finish the language-neutral Unicode version and collection-scope rules for
  versioned file-profile contracts;
- report decodability per stream and support exact stream or portable-member
  selection without adding a query language;
- validate transactional commit and abort with an adversarial non-filesystem
  carrier; and
- finish installation and release guidance, and verify first-party contract
  URLs from an anonymous client.

The first compatibility promise remains unfrozen until cross-language recovery
and constrained-memory streaming have been reproduced from the public
specification and vectors.

## Next: `0.3-apple` producer identity

The next manifest revision will describe the implementation that wrote one
concrete container representation. A bounded canonical producer identity will
contain a stable implementation name and version, language name and version,
and an optional runtime name and version.

Producer identity is advisory and untrusted. It never changes validation,
decoding or compatibility behavior. Inspection will report the container's
producer separately from the local inspector, and repacking will record the
repacker as the new producer. Samples, vectors, CLI version output and both
human and JSON inspection output will change together.

## Later: production encoding

Production tuning will use the ordinary registry and Recipe execution path. A
typed bounded tuner will try an explicit candidate set, always include the
identity Recipe, require exact round trips and deterministic tie-breaking, and
return the already encoded winner. A high-level packager can then deduplicate
selected Recipes and use bounded spooling to finalize a manifest without
teaching the wire writer about search policy.

Measured benchmark definitions will compare conventional archives, fixed OBST
and tuned OBST on reproducible telemetry, heterogeneous and large real-world
inputs. New reversible Stages will land only after their wire parameters,
inverse, malformed-input behavior, allocation bounds and measured value are
known.

Research prototypes become candidates only after they are rebuilt against the
public APIs and real OBST wire format. Temporary mock containers are not
migration targets.

## Later: seekable and indexed access

`0.2-apple` deliberately keeps `CMIT` as the absolute end of the container and
the core reader single-pass. Seekable access must remain optional tooling, not
a new validity requirement.

The first useful step is a rebuildable sidecar index. It can map stream and
chunk identities to byte offsets and sizes, bind itself to the terminal commit
hash, and be discarded or regenerated without changing the container it
describes. A container without that index remains fully valid and recoverable.

A later wire revision may permit the same index payload in explicitly separate
auxiliary data after `CMIT`. That revision must define new trailing-byte and
binding semantics rather than weakening `0.2-apple` retroactively.

## Later directions

- Transport-neutral capability negotiation may let a sender choose only Stage
  decoders and stream profiles already supported by a receiver. It will never
  download or activate code.
- Selective and nested tooling may build on the optional index while preserving
  bounded access and the existing single-pass reader contract.
- Content-defined chunking may improve chunk reuse across insertions while the
  wire format continues to see ordinary bounded chunks.
- Incremental packing, append and delta snapshots require explicit crash,
  identity, chain-depth and publication contracts before implementation.
- Repacking may change stored representation while preserving verified logical
  bytes, metadata and stream identity.
- Signatures, deduplication, directory-tree profiles and global archive
  transforms remain unassigned ideas until a concrete threat model or measured
  use case requires them.
- Further security scanning may add Bandit and Semgrep once each
  tool has a reviewed baseline and an explicit place in the quality gate.
