# OBST: OBST Binary Storage & Transformations

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

<p align="center">
  <img src="docs/assets/Hero.png" alt="OBST logo: a layered apple-shaped binary container" width="960"><br>
<sub>Illustration generated with ChatGPT.</sub>
</p>

> **Obst** /oːpst/, German, neuter noun<br>
>
> 1. fruit, collectively<br>
> 2. also a (recursive) binary container

## What is OBST?

OBST is a federated representation layer for logical byte streams. It separates
the bytes your application uses from the way those bytes are stored: a database,
measurements and images can share a container while using different reversible
representations.

You can wrap existing data or build your own binary format on top, without
reinventing framing, chunking, integrity checks and representation pipelines.
OBST does not try to replace SQLite, MCAP, JPEG or other domain formats.
Their bytes keep their meaning; your application still owns its schema and rules.

**OBST is the format. The OBST toolchain is the reference ecosystem around
it.** Anyone may implement the [wire contract](docs/format.md) independently
of the Python toolchain. The format is experimental and compatibility has
[not frozen](#status).

For a taste of what those boundaries allow, jump to [Eldritch horrors](#eldritch-horrors):
custom formats, new representations of the same data and archives carrying
their own decoder sources.

## Try it in 20 seconds (I timed it! :D)

The reference toolchain requires Python 3.14. From a checkout:

```bash
git clone https://github.com/SmolBlackHole/Obst.git
cd Obst
python -m pip install . ./plugins/defaults
obst plugins enable obst-defaults
obst inspect samples/apple.obst
```

Inspection checks the stored container and its completeness without decoding
the JPEG inside. Among the reported fields are:

```text
Streams                       1
Recipes                       1
Chunks                        6
Required decoders available   yes
Logical recovery              not attempted
```

The defaults plugin also supplies packing and extraction. Try bundling two
files from this checkout:

```bash
obst pack README.md CONTRIBUTING.md -o fruit.obst
obst unpack fruit.obst -o restored
obst inspect fruit.obst --json
```

The recovered files appear under `restored`. The [CLI guide](docs/toolchain/cli.md)
covers the commands, with [human-readable](docs/toolchain/cli-output-reference.md)
and [JSON](docs/toolchain/cli-json-output-reference.md) output references.
Sample images and attribution live in [`samples/`](samples/).

The `obst` distribution supplies the runtime, plugin manager, CLI host and
native inspection. `obst-defaults` supplies replaceable first-party Extensions
and file commands. Installation makes a plugin discoverable; enabling, selecting
or explicitly testing it is the separate host decision that permits its code
to execute.

## Where OBST fits

```text
       Your format / protocol / package
                       |
             Application semantics
                       |
                Stream profiles
                       |
                 Logical bytes
                       |
       +------------- OBST -------------+
       | Framing and chunking           |
       | Recipes and contract IDs       |
       | Integrity and completeness     |
       +--------------------------------+
                       |
 Caller-selected carrier / storage / transport
```

Take a firmware bundle: one stream contains an application manifest, another
the firmware, and others resources. Your format defines device compatibility,
how the streams relate and how installation works. OBST does not need to know
that the container is a firmware bundle.

A **stream profile** defines the meaning of a stream's logical bytes and metadata.
Those bytes are split into **chunks**. Each chunk names a **Recipe**, an ordered
pipeline of reversible processing steps called Stages. For example, a bundle
could choose these representations:

| Logical content | Possible Recipe |
| --------------- | --------------- |
| Application manifest | Identity, leaving the bytes unchanged |
| Numeric calibration data | Delta8 followed by zlib |
| Already compressed images | Identity |

The same mechanism can store existing formats, bundle heterogeneous data,
support a new domain format or compare representation strategies.

A `.obst` file is one destination. Memory, database BLOBs, object stores and
pipes can carry the same byte stream. OBST does not require a filesystem or
seeking; the caller supplies storage and transport.

## How does the container work?

The bundle's stream declarations and Recipes go into OBST's container manifest,
separate from its application manifest. An OBST byte stream contains this
manifest, independently framed chunks and a terminal commit. The manifest
declares streams, Recipes and contracts before payloads arrive. Writers must
finalize it first, which can require spooling
when an encoder discovers Recipes by searching. The terminal commit establishes
completeness: ending at a clean chunk boundary is still truncation.

A Recipe runs forward while encoding and backward while decoding. The invariant
is byte-exact:

```text
decode(encode(logical_bytes)) == logical_bytes
```

A Recipe may contain no Stages. That is the identity representation: stored
bytes equal logical bytes and no Stage decoder is required. Compression is
optional.

**Self-describing** means the container describes its structure, contract
references and representation pipelines. It does not automatically include
the specifications or implementations of every referenced contract.
Four questions therefore remain separate:

- Is the container structurally valid and complete?
- Are the required Stage decoders available?
- Do the recovered logical bytes pass verification?
- Does the application understand the stream's meaning?

A missing Stage decoder leaves affected payloads unavailable, not structurally
corrupt. An unknown stream profile alone does not prevent verified byte recovery
when the required Stages are supported. Integrity checks do not establish
publisher authenticity. The [validity and recovery rules](docs/format.md#validity-availability-and-recovery)
define what each check establishes. The [anatomy guide](docs/anatomy.md)
follows the complete path from logical bytes to container and back.

## Who owns what?

| Owner | Responsibility |
| ----- | -------------- |
| Application | Meaning, schemas, units, record layouts and relationships between streams |
| OBST | Container structure, contract declarations, Recipes, reconstruction rules, integrity checks and completeness |
| Extension publisher | Stream-profile and Stage semantics, decoding rules and compatibility of its versioned contracts |
| Caller | Storage, transport, encoder strategy and trusted decoder implementations |

The common wire layer stays narrow. New domain formats, codecs and tools can
be added through these boundaries without teaching the OBST wire format their
application semantics. The [design notes](docs/design.md) explain why.

## Federated contracts, independent compatibility

Publishers define stream profiles and Stages in namespaces they control.
You can publish and evolve your own contracts without waiting for a central
registry's approval or a new OBST release. Implementations exchange data by
honoring the same versioned contracts, regardless of who wrote them.

| Contract | What its version governs | Who maintains compatibility |
| -------- | ------------------------ | --------------------------- |
| OBST wire format, such as `0.2` | Layout, framing, references, integrity and completeness | OBST's specification and implementations |
| Stream profile or Stage, such as `org.acme/telemetry@7` or `org.acme/fancy-delta@3` | Stream meaning and metadata, or reversible processing and parameters | The contract's publisher and implementations |

The Acme IDs are illustrative. They can coexist with first-party contracts in
one OBST `0.2` container. An incompatible contract change gets a new `@N`;
it does not silently redefine the old ID. An ID identifies the contract, not
a Python class, distribution or implementation. The
[identity rules](docs/format.md#extension-table) apply equally to first-party
and third-party Extensions.

The same OBST version does not imply support for every payload. Applications
must choose a shared set of contracts. Preserving a domain's old contracts and
usable decoders belongs to its publishers and consumers; OBST does not absorb
their migrations or promise to ship every historical decoder.

## Can I extend it?

Yes. `obst.bytes@1` is the one core stream contract. The shipped zlib, Delta8
and portable-file capabilities are ordinary Extensions from `obst-defaults`.
Third-party Extensions use the same registry and provider contracts.
There is no first-party VIP entrance.

Beyond wire-visible Stages and stream profiles, you can supply a Carrier for
storage or transport, or a Packager for encoding policy. Those are runtime
capabilities selected by the host. A plugin can distribute them alongside
commands, resource definitions, limit profiles and conformance cases.
Only Stage and stream-profile IDs enter container bytes; those bytes cannot
install, enable or select executable code.

The encoder may be simple or absurdly sophisticated. It may optimize size,
memory, encode time, decode time or flash usage, or consult the alignment of
the planets and stars. The container stores the winner, not the encoder's
emotional journey. The [Adaptive-Zlib example](examples/plugin_adaptive_zlib/README.md)
demonstrates adaptive choices inside one Stage through the public APIs.

Start with the [Extension guide](docs/toolchain/extensions.md) to choose a
boundary, or the [plugin guide](docs/toolchain/plugins.md) to distribute
capabilities through the Python host.

## Eldritch horrors

The existing rules permit more than the original power-meter experiment had
any business needing. These are application constructions, not a list of
finished products:

| You could build ... | Because ... |
| ------------------- | ----------- |
| [Your own format](docs/eldritch_horrors.md#a-format-for-building-formats) | Application rules and versioned stream profiles can sit above unchanged OBST framing. |
| [Several unrelated worlds in one container](docs/eldritch_horrors.md#several-unrelated-worlds-in-one-container) | Different domains and contract versions can coexist with independent Recipes. |
| [A new representation of the same data](docs/eldritch_horrors.md#repacking-without-changing-the-data) | Verified logical bytes can be written again using different Recipes. |
| [One container for different reader capabilities](docs/eldritch_horrors.md#capability-tiers-and-different-machines) | Applications can offer separate streams and recover only the supported ones. |
| [Data archaeology kits](docs/eldritch_horrors.md#data-archaeology-kits) | Ordinary streams can carry specifications, decoder sources and conformance vectors. |
| [OBST containing OBST](docs/eldritch_horrors.md#obst-containing-obst) | Both are bytes. This was apparently enough permission. |

Telemetry exports, research datasets, ML artifacts, backups and firmware bundles
are possible applications of those boundaries. [The full chapter](docs/eldritch_horrors.md)
also explores shared dictionaries, network envelopes and domain-specific
toolchains, including what each application must still implement.

## When does it make sense?

| OBST starts to make sense when ... | Prefer something else when ... |
| --------------------------------- | ------------------------------ |
| Streams benefit from different reversible representations | ZIP or an established container already fits |
| Representation should change without changing application meaning | Only the smallest compressed file matters |
| Framing must remain inspectable without every decoder installed | You need queries, indexes or transactions from the container |
| A new domain format needs chunking, integrity and finite streaming | An existing domain format already owns those concerns |

Honestly, you probably should not use OBST merely because some bytes exist.
It provides neither a universal application schema nor a universal compression
strategy. Streaming means a finite, manifest-first container, not an endless
interactive protocol. Decoder distribution and application security remain
explicit responsibilities.

### Status

OBST is experimental. The v0.2 conformance vectors pin the `0.2-apple` draft,
but compatibility has not frozen. Intentional pre-freeze wire changes regenerate
the vectors and samples. The reference runtime reads, writes and inspects
bounded chunked containers.

Preserved cross-language recovery, constrained-memory results, longer-running
fuzzing, production tuning and real workload benchmarks remain open.
Architectural suitability does not establish production readiness or long-term
archive guarantees. The [roadmap](ROADMAP.md) tracks the remaining work.

## Choose your next step

| I want to ... | Start here |
| ------------- | ---------- |
| Understand the mechanics | [Container anatomy](docs/anatomy.md) |
| Use OBST from Python | [Toolchain guide](docs/toolchain/README.md) |
| Define a contract or contribute a capability | [Extension guide](docs/toolchain/extensions.md) |
| Implement OBST independently | [Wire specification](docs/format.md) and [conformance evidence](docs/toolchain/conformance.md) |
| Explore all reading paths | [Documentation index](docs/README.md) |
| Contribute or report a vulnerability | [Contributing](CONTRIBUTING.md) or [security policy](SECURITY.md) |

## How this happened

This did not start as a plan to invent another container format.

Around 2023 or 2024, early in my studies and roughly in my third semester, I
got a Shelly Smart Plug. I wanted to know how much energy my setup used and
switch it off while I was away instead of quietly paying for idle power.

The original plan was small: a battery-powered ESP would poll the Shelly and
store measurements in flash. I had no database ready, so the device needed a
compact local format. I wrote one, including a compression pipeline for the
sensor readings.

I found the code again a few years later. The Shelly-specific parts were less
interesting than the pipeline, so I started feeding it other things: images, a
database, source code, plain text and my bachelor's thesis. Then I put an OBST
file through it. That worked too.

The trick was not Shelly data. It was bytes. The pipeline rearranged them so
zlib could see patterns it had missed before. Turning that into a general
container was the next logical step.

Logical in the sense that packing OBST inside OBST can be called logical.

$$ OBST(OBST(OBST(...))) $$

The name came from an endian bug in the old prototype. It represented the ASCII
magic `OBST` as the integer `0x4F425354` and serialized that integer
little-endian. The file began with:

```text
54 53 42 4F
 T  S  B  O
```

TSBO was not intentional. I fixed the bug but the fruit stayed. Why OBST?
Honestly, I have no idea. It was a placeholder and I like fruit.

## Spare a starfruit? ⭐ :D

If you've read this far, consider leaving a star on the repository.
It helps me see that people are interested in the project and gives me
another excuse to keep turning random things into fruit. Thank you! :D

## License

This is a multi-license repository. File-level SPDX metadata and `REUSE.toml`
are authoritative.

| Material                                                   | License                                              |
| ---------------------------------------------------------- | ---------------------------------------------------- |
| OBST format specification, Anatomy, Design and normative contracts | [CC BY 4.0](LICENSES/CC-BY-4.0.txt)                  |
| Reference implementation, tooling and general project docs | [MPL 2.0](LICENSES/MPL-2.0.txt)                      |
| Unsplash sample images and containers that embed them      | [Unsplash License](LICENSES/LicenseRef-Unsplash.txt) |

The [name-use policy](TRADEMARKS.md) permits truthful compatibility claims and
reserves official project identity. Citation metadata lives in
[`CITATION.cff`](CITATION.cff). Independently written Extensions may use
another license, but first-party wire-visible contracts must document how to
recover their logical bytes.
