# OBST Roadmap

This file is the single backlog for unfinished OBST work. It records direction
and delivery order, not supported behavior or wire-format rules.

Use the other documents for present behavior:

- [README.md](README.md) introduces OBST and shows the working surface.
- [docs/format.md](docs/format.md) is the normative byte-level specification.
- [docs/cli.md](docs/cli.md) documents the installed command line.
- [docs/README.md](docs/README.md) indexes the public documentation.
- [docs/extensions/README.md](docs/extensions/README.md) documents the Python
  extension system.
- [docs/design.md](docs/design.md) explains architectural decisions.

Unchecked items below are proposals until their implementation, tests and
authoritative documentation land together. CLI spellings are not reserved by
this roadmap.

## Current position

| Area                         | State        | Evidence or remaining boundary                                                                        |
| ---------------------------- | ------------ | ----------------------------------------------------------------------------------------------------- |
| Repository foundation        | Active       | MPL-2.0 licensing, packaging and strict development checks work                                       |
| v0.1 wire format             | Specified    | Specification lives in `docs/format.md`; published vectors live in `conformance/`                     |
| Reader and writer            | Implemented  | Chunking, limits, integrity and unknown stages are tested                                             |
| File archive CLI             | Implemented  | Bounded extraction, handle-bound sources, redirected-root rejection and inert recovery are tested     |
| Extension API                | Implemented  | First-party and third-party distributions use instance-local plugin and registry composition          |
| Carrier and packager API     | Implemented  | Fixed packaging and publication lifecycle are separated                                               |
| Producer provenance          | Planned      | Requires the next manifest revision before production tuning                                          |
| Production tuner/packager    | Planned      | The reference implementation has no automatic recipe search                                           |
| Independent interoperability | Demonstrated | 2 reported clean-room readers recovered historical and current nested samples; vectors are checked in |

## Now: stabilize the core contract

No new production transform should land before this section is closed.

### Conformance gaps

- [x] Require one terminal commit that detects complete chunk-suffix removal
      without making the writer seek or know final counts before streaming.
- [x] Regenerate the v0.1 golden vector and checked-in samples with that
      commitment before compatibility freezes.
- [x] Cover invalid and oversized stage parameters and stream metadata.
- [x] Cover duplicate IDs, unknown references and non-canonical manifest
      ordering systematically.
- [x] Add property-based round-trip tests for every production stage across
      varied payload lengths.
- [x] Add a decode-only, multi-chunk Delta8 plus zlib golden vector without
      requiring bit-identical output from different conforming zlib encoders.
- [x] Demonstrate that an independent clean-room reader can recover a real
      non-RAW sample from the pre-terminal draft without using the Python
      reference implementation.
- [x] Repeat independent recovery against the current terminal-commit draft.
- [x] Publish reusable Golden, valid and isolated invalid vectors with a
      machine-readable language-neutral catalog.
- [ ] Preserve an independent reader implementation and run log as
      repository-verifiable conformance evidence.
- [x] Add a mutation matrix for every container, manifest and chunk header
      field, including manifest-version mismatches.
- [x] Add explicit RAW-in-RAW conformance coverage without automatic opening.
- [x] Distinguish recoverable payload bytes from understood stream semantics.
- [x] Validate bounded chunking and byte-exact recovery with real application
      data.

### Extension API

- [x] Implement the approved
      [capability-based provider model](docs/extensions/stages.md#provider-protocols):
      self-describing stage objects bind exact parameters to reusable
      directional encoders and decoders without a mandatory two-way ABC.
- [x] Add immutable `ExtensionDescriptor` metadata, a mutable instance-local
      `ExtensionRegistryBuilder` for composition and an immutable
      `ExtensionRegistry` for operations. One registered extension object
      contributes every capability it implements; no decorator or assembly
      wrapper provides a second registration path.
- [x] Move every built-in stage through the public provider and registry path;
      do not retain a privileged built-in execution path.
- [x] Replace ambiguous `supports()` checks with `can_encode()`, `can_decode()`,
      `require_encoder_provider()` and `require_decoder_provider()`. Reject
      duplicate directions and conflicting descriptors deterministically.
- [x] Add optional declared specification URLs to manifest extension entries.
      Keep the ID authoritative, treat the URL as untrusted advisory data and
      never fetch, download or execute anything during inspection.
- [x] Validate all recipe parameters before the writer publishes header bytes,
      pass output budgets to both directions and verify provider output sizes
      in the executor.
- [x] Distinguish expected stage rejection from unexpected provider failures
      without hiding the original implementation error.
- [x] Keep direct recipe execution, directional recipe sessions and
      provider-facing validation helpers in the supported public API for
      tuners, conformance suites and custom packagers.
- [x] Publish a pytest-independent Stage conformance helper and a public
      container-vector corpus.
- [ ] Add contract-specific Stage and stream-profile vector bundles maintained
      by independently implemented third-party providers.
- [x] Add focused zlib rejection tests for truncated, trailing and concatenated
      streams plus Delta8 known-answer and per-chunk reset vectors.
- [ ] Define the Unicode version used by versioned profile normalization and
      case-folding contracts.
- [ ] Define whether a versioned file-profile collection spans every matching
      stream in a container, a selected subset or only a pure file archive.
- [x] Define zlib compression levels as language-neutral encoder hints and
      allow providers to map all values to the closest backend settings.
- [x] Report stream-profile metadata encoding, decoding and interpretation
      separately from Stage execution capabilities in the immutable registry
      inventory and CLI.
- [x] Treat inspection JSON as a public tooling API and test incompatible
      schema-version changes.

### Plugin discovery

- [x] Define a Python plugin as an installable distribution that exports one
      or more ordinary extension values; do not make it a second extension API.
- [x] Add explicit, opt-in installed-package discovery without process-global
      registry mutation or import-time registration side effects.
- [x] Keep direct imports and explicit `ExtensionRegistry` construction as a
      supported path and use that path in core and conformance tests.
- [x] Define entry-point identity, load failures, duplicate contracts and trust
      policy before the reference CLI enables discovered extensions.
- [x] Treat third-party CLI commands and archiver discovery as separate design
      problems rather than consequences of stage discovery.
- [x] Publish and load first-party Extensions through the same installed plugin
      factory contract while keeping core tests independent of discovery.
- [x] Centralize discovery, persistent enable/disable state, runtime composition
      and capability inventory in one public `PluginManager`.
- [x] Publish optional portable Stage cases through a matching
      `obst.conformance` contribution and expose explicit plugin testing.
- [x] Extract first-party tooling into the ordinary `obst-defaults`
      distribution. Installing `obst-defaults` does not activate it; the host
      must enable it through the same explicit path used by third-party
      plugins.

### Carrier and packager boundary

- [x] Start after the capability-based stage registry is stable, because the
      generic packager depends on the public recipe executor and registry.
- [x] Expose the existing minimal blocking binary reader and writer contract as
      supported API. Reuse Python's structural I/O protocols instead of adding
      parallel OBST base classes.
- [x] Define a generic packager over declared logical streams and bounded chunk
      sources. It accepts an already opened binary writer and never requires a
      filesystem path.
- [x] Keep carrier lifecycle separate from the binary data plane. An optional
      adapter owns open, close, commit and abort for a filesystem destination,
      database transaction or multipart object upload.
- [x] Validate that lifecycle contract against the filesystem carrier and at
      least one second carrier with different commit and abort behavior before
      freezing it.
- [x] Register carrier and packager capabilities through the same immutable
      `ExtensionRegistry` used by stages and stream profiles. Keep their IDs
      runtime-only and never serialize them into container bytes.
- [x] Deliver first-party filesystem, memory, stdin and fixed-packaging
      providers through the same activated plugin factory as third-party
      extensions; the CLI resolves them rather than constructing providers.
- [ ] Add an adversarial transactional carrier beyond the filesystem adapter
      and prove commit and abort behavior under injected write failures.
- [ ] Keep efficient range reads and selective remote extraction separate; they
      need an index and resource policy, not a larger storage interface.

### Inspection capability

- [x] Record the recipes actually referenced by each stream's chunks and show
      the declared default recipe separately.
- [ ] Report decodability and missing stages per stream; used recipe chains are
      already reported.
- [x] Derive the container-wide result from recipes that are actually used.
      Unused recipes and empty streams must not create false capability errors.
- [ ] Allow outer inspection to select streams by exact ID and file members by
      exact portable name.

### Producer and implementation identity

- [ ] Introduce producer provenance as part of `0.2-apple` instead of silently
      changing the specified `0.1-apple` manifest layout.
- [ ] Define one bounded, canonical `ProducerIdentity` containing a stable
      implementation name and version plus a language name and version.
- [ ] Allow an optional runtime name and version. Version values remain strings
      because Python `3.14`, C++ `23` and Rust `2024` do not share one numeric
      component model.
- [ ] Store the producer identity in the manifest. It describes the
      implementation that wrote this concrete container representation, not
      the origin of its logical data.
- [ ] Keep producer provenance advisory and untrusted. A reader never changes
      validation, decoding or compatibility behavior based on the claimed
      implementation, language or runtime.
- [ ] Report `producer` from the container and `inspector` from the local
      process as separate identities in human and schema-versioned JSON output.
- [ ] Make `obst --version` identify `obst-python`, its package version, Python
      language line, concrete runtime and supported OBST format line.
- [ ] On repacking, record the repacker as the new producer. Do not add producer
      history, attestation or per-stage provider provenance in this revision.
- [ ] Rebuild samples and golden vectors with explicit deterministic producer
      identities and cover malformed, oversized and non-canonical fields.

Acceptance requires an `obst-python` container to retain its producer identity
when inspected by another process, while the report independently identifies
the inspecting implementation. A future `obst-cpp` or `obst-rust` writer must
be able to populate the same model without Python-specific placeholder fields.
Cross-language conformance still depends on byte-exact logical recovery, not on
trusting the producer claim or requiring different encoders to emit identical
compressed payload bytes.

## Next: production encoding

### Candidate stages

- [ ] Evaluate reversible XOR8 and byte shuffle only after their parameter
      encoding, inverse, malformed-input behavior and allocation limits are
      specified.
- [ ] Add integer-oriented stages only after width, signedness, byte order,
      count and overflow behavior are explicit.
- [ ] Keep float quantization outside reversible stages. An application-owned
      fixed-point stream type must define an exact decimal exponent, rounding
      behavior and rejected values.
- [ ] Define record-aligned chunking or split-record behavior before a stage
      depends on record boundaries.
- [ ] Add more candidates only when measurements show useful gains.

The first candidate set stays deliberately small: RAW, zlib, delta8 plus zlib,
XOR8 plus zlib, and byte shuffle plus zlib for a few explicit widths.

### Typed tuner

- [ ] Replace stringly typed Lab results with typed candidates and results
      built from production `Recipe` and `StageSpec` values.
- [ ] Execute candidates through the production registry and recipe executor.
- [ ] Let policy provide an explicit bounded candidate set; always include RAW.
- [ ] Require exact round-trips, a configurable minimum gain and deterministic
      tie-breaking.
- [ ] Return the already encoded winner so packaging does not execute it twice.
- [ ] Record raw size, codec-only size, selected size, gain and encode time.
- [ ] Include chunk framing, parameters and newly introduced manifest recipes
      in size comparisons.
- [ ] Enforce candidate, time, memory and intermediate-output budgets.

Acceptance requires structured bytes to select a useful candidate, random or
already compressed bytes to fall back to RAW, and identical input plus policy
to produce the same byte-exact result.

### High-level packager

- [ ] Accept logical byte streams and stream-owned metadata without turning the
      low-level writer into a policy object.
- [ ] Split inputs into bounded chunks and support per-stream or per-chunk
      tuning policy.
- [ ] Deduplicate selected recipes and assign deterministic recipe IDs.
- [ ] Choose deterministic stream defaults while allowing declared per-chunk
      recipe overrides.
- [ ] Store only used recipes and required stages in the final manifest.
- [ ] Add a bounded writer path for already encoded tuner winners.
- [ ] Use a two-pass spool for recipe discovery: tune and spool chunks, finalize
      the manifest, then write the container.
- [ ] Keep fixed-recipe non-seekable input single-pass. A stdin archive member
      requires explicit stream metadata and a portable filename.
- [ ] Verify bounded RAM use with input larger than the configured memory
      budget.

Acceptance requires different streams and chunks to select different recipes,
byte-exact recovery through the normal reader, deterministic recipe IDs and
bounded behavior for both seekable and non-seekable input.

### Reproducible benchmark and demo corpus

- [ ] Build checked-in benchmark definitions for telemetry, a heterogeneous
      dataset and a large real-world directory tree such as a Minecraft world.
- [ ] Record source provenance, licenses, hashes, tool versions and exact
      commands without committing private or redistributable input data.
- [ ] Compare raw input, one conventional archive baseline, fixed-recipe OBST
      and tuned OBST with the same logical contents.
- [ ] Report container size, encode and decode time, peak memory and the recipes
      selected for each stream or chunk.
- [ ] Generate the README showcase from measured results instead of maintaining
      illustrative numbers by hand.

Acceptance requires another machine to reproduce the published table from the
recorded inputs and commands within documented environmental variance.

### Capability negotiation

- [ ] Define a transport-neutral capability document through which a receiver
      advertises the versioned stage decoders it accepts, the stream profiles
      it understands and the resource limits relevant to encoding choices.
- [ ] Treat HTTP, WebSocket, message protocols and other bindings as
      replaceable runtime adapters. Negotiation does not create a manifest
      extension ID or a second OBST byte format.
- [ ] Let a sender select only compatible recipes, finalize the manifest and
      then stream an ordinary OBST header, manifest and chunks without
      materializing the complete container.
- [ ] Allow a stronger intermediary to decode and repack logical bytes for a
      receiver with a different capability set, subject to the ordinary
      integrity and resource limits.
- [ ] Treat advertised capabilities as untrusted input. Define version
      matching, unknown IDs, size ceilings, downgrade policy and failure before
      any transport binding is considered stable.
- [ ] Keep automatic decoder download and execution outside negotiation. A peer
      advertises local capabilities; it does not ask OBST to install code.

Acceptance requires an embedded producer with a small fixed capability set to
emit valid OBST that a negotiated server can decode, and a server to repack the
same logical bytes for another receiver before immediately streaming the new
manifest and chunks.

### Content-defined chunking

- [ ] Add an optional deterministic chunking policy with explicit minimum,
      target and maximum chunk sizes. Evaluate a FastCDC-style algorithm
      without making that name part of the contract before measurements exist.
- [ ] Keep chunk-boundary discovery in the packager. The wire format continues
      to see ordinary chunks and does not learn why a boundary was selected.
- [ ] Preserve stable chunk boundaries across local insertions and deletions so
      incremental operations do not invalidate every following fixed-size
      chunk.
- [ ] Bound CPU work, memory use and the number of tiny chunks under adversarial
      input. Record every algorithm parameter needed for deterministic reuse.
- [ ] Compare fixed-size and content-defined policies on realistic files,
      databases and archive revisions before selecting first-party defaults.

Acceptance requires a small insertion near the beginning of a payload to leave
most later chunk hashes reusable while exact reconstruction remains independent
of the chunking policy.

## Later: archive and recursive tooling

### Archive boundary cleanup

- [x] Start this refactor after the capability-based stage registry is stable,
      and after the carrier and packager boundary is implemented.
- [x] Separate the portable `obst.file@1` metadata contract, logical member
      planning and recipe selection from filesystem paths, temporary output and
      atomic publication.
- [x] Make the CLI compose those library layers while preserving the existing
      explicit-file pack and safe-unpack behavior.
- [x] Implement the built-in filesystem path through the same public packager
      and carrier contracts available to third-party integrations.

### Nested inspection

- [ ] Inspect an explicitly selected inner stream only after the outer stream
      is decodable and recovered within resource budgets.
- [ ] Distinguish missing outer stages, ordinary recovered bytes, invalid inner
      framing and a valid inner container with missing stages.
- [ ] Require explicit selection at every nesting level and bound depth,
      cumulative decoded bytes, manifests and chunk counts.
- [ ] Never recurse from a filename suffix or leading magic bytes alone.

### Repacking

- [ ] Implement bounded outer repacking first, preserving stream declarations,
      chunk boundaries and decoded logical bytes.
- [ ] Define `outer`, `nested` and `flatten` as separate preservation contracts.
      Cross-stream `global` transforms belong to a future versioned archive
      profile, not ordinary chunk recipes.
- [ ] Support bounded `auto`, `memory` and `tempfile` spooling policies where a
      mode needs intermediate materialization.
- [ ] Write to a separate temporary output, validate it completely and publish
      only on success without overwriting.
- [ ] Report before and after sizes without publishing partial results.

### Append and incremental snapshots

Treat these as three separate operations with different preservation rules:

1. **Append** continues an existing declared stream at its next sequence
   number. It may use only streams, recipes and extensions already present in
   the immutable manifest unless a future format explicitly changes that rule.
2. **Incremental pack** creates a complete new container while reusing
   unchanged work from a previous container.
3. **Delta snapshot** stores a versioned reconstruction contract relative to a
   known base snapshot rather than pretending to be a standalone full archive.

- [ ] Define append-capable carrier behavior separately from ordinary output
      publication. Immutable object stores and database BLOBs do not gain
      append merely because a filesystem can seek to the end of a file.
- [ ] Define crash, truncation, concurrency and validation rules before an
      appender writes the first new chunk. It must recover the next per-stream
      sequence without trusting an unvalidated tail.
- [ ] Let incremental packing compare logical size, logical chunk hash, stream
      identity, metadata and recipe contract before reusing an encoded payload.
      A hash match alone must not silently cross semantic or trust boundaries.
- [ ] Reuse encoded payload bytes only when the selected stage IDs and parameter
      bytes are compatible. Rebuild framing when stream, sequence or recipe IDs
      change, and retune only data whose desired representation changed.
- [ ] Define a versioned delta-snapshot profile with a canonical base identity,
      stream additions and deletions, metadata changes and chunk replacement
      operations. Do not overload one chunk's BLAKE2s-128 value as the identity
      of an entire snapshot.
- [ ] Bound delta-chain depth, cumulative decoded bytes and missing or circular
      base references. Reconstruction must fail without publishing a partial
      snapshot.
- [ ] Let the repacker materialize `base + deltas` as a fresh standalone OBST
      container and verify its logical snapshot before publication.

Acceptance uses a base containing `A, B, C, D` and a revision containing
`A, B', C, D, E`: unchanged logical chunks are reused, changed and new chunks
are processed, and materializing the base plus its delta yields exactly the new
logical snapshot.

### Selective extraction and non-seekable input

- [ ] Select archive members by repeated exact stream IDs or portable names;
      keep globs and query languages out of the first implementation.
- [ ] Validate every selector and output collision before publishing anything.
- [ ] Accept non-seekable members only with explicit metadata and bounded
      spooling when required. Reject ambiguous multiple-stdin input.

## Publication and compatibility

- [ ] Select a license before presenting the repository as licensed OSS.
- [ ] Make every first-party extension URL anonymously reachable before public
      distribution. Rebuild samples when a wire-visible `specification_url`
      changes.
- [ ] Remove or sanitize private fixtures and generated databases.
- [ ] Add contribution, security and release guidance when external
      contributors or a first release make them useful.
- [ ] Implement a small independent reader, likely in C or C++, against the
      published golden vectors.
- [ ] Test constrained-memory and streaming behavior across implementations.
- [ ] Freeze the first compatibility promise only after cross-language
      conformance succeeds.

## Unassigned ideas

These remain ideas, not implied format behavior:

- indexed or seekable readers
- parallel decoding with ordered result assembly
- interrupted-write resynchronization
- in-place mutation and its consistency model
- directory trees and filesystem metadata profiles
- automatic decoder download or execution
- global archive transformations and cross-file compression
- deduplication and content-addressed storage
- signatures after a threat model and ownership exist
- `OBSTkorb` as a versioned cold-storage profile
- DAG recipes instead of the implemented linear pipeline
