# OBST: OBST Binary Storage & Transformations

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

<p align="center">
  <img src="docs/assets/Hero.png" alt="OBST logo: a layered apple-shaped binary container" width="960"><br>
<sub>Illustration generated with ChatGPT.</sub>
</p>

> The fruity open container format.

> **Obst** /oːpst/, German, neuter noun<br>
>
> 1. fruit, collectively<br>
> 2. also a (recursive) binary container

## What is OBST?

OBST is a self-describing, streamable representation layer for logical byte
streams. It separates what those bytes mean from how they are stored, then
describes the stored form through open, versioned and reversible pipelines.

**OBST is the format. The OBST toolchain is the reference ecosystem around
it.** This repository contains both, but they are not the same thing.

OBST sits below domain models and above storage or transport:

| Layer                             | Game example          | Telemetry example |
| --------------------------------- | --------------------- | ----------------- |
| Application semantics             | Game state            | Telemetry model   |
| Domain format                     | SQLite                | MCAP              |
| Logical bytes                     | SQLite database bytes | MCAP bytes        |
| **[OBST format](docs/format.md)** | **OBST**              | **OBST**          |
| Storage or transport              | S3 object             | Flash             |
| Actual transport                  | HTTP over TCP         | Block device      |

The application owns meaning. OBST owns the reversible representation of its
logical bytes. A carrier owns where the resulting OBST byte stream goes. A
`.obst` file is one option, as are memory, a database BLOB, an object store or
anything else that can carry binary data without getting creative about it.

The versioned [format specification](docs/format.md) is the canonical
definition of valid OBST bytes. Anyone may implement that contract. Modified
specifications and incompatible formats do not become official OBST revisions;
the [name-use policy](TRADEMARKS.md) keeps interoperability separate from
project identity.

## What can you build with it?

OBST is deliberately below any one application. It can wrap an existing
format, bundle unrelated logical streams or provide the representation layer
underneath a new domain-specific format.

| Use                                    | What the application owns                      | What OBST contributes                             |
| -------------------------------------- | ---------------------------------------------- | ------------------------------------------------- |
| Store an existing format               | SQLite, MCAP, JPEG, Parquet or other bytes     | Chunking, reversible representation and integrity |
| Bundle heterogeneous data              | Relationships between metadata, samples, media | Independent streams with independent Recipes      |
| Build a new domain format              | Mail, telemetry, game or model semantics       | Framing plus versioned stream and Stage contracts |
| Experiment with stored representations | Candidate selection and tuning policy          | A decoder-visible record of the selected pipeline |

A telemetry export, for example, could contain:

```text
metadata and schema    -> identity Recipe
numeric sample blocks -> delta8 -> zlib
compressed images     -> identity Recipe
complete container    -> streamed to S3
```

A mail service could define one stream profile for messages and another for
attachments. A game could define profiles for world state or assets. Those
profiles own the domain meaning; OBST still sees versioned metadata and logical
bytes.

That also makes OBST a possible foundation for another file format. The new
format defines its stream profiles and application rules, while OBST supplies
the byte-stream container underneath them.

## When should you use it?

Honestly, you probably should not use OBST merely because some bytes exist.
Established formats have ecosystems, mature tooling and fewer ways to surprise
your future self.

| OBST starts to make sense when ...                              | Prefer something else when ...                         |
| --------------------------------------------------------------- | ------------------------------------------------------ |
| streams benefit from different reversible representations       | ZIP or another established container already fits      |
| representation must change without changing application meaning | only the smallest compressed file matters              |
| framing must remain inspectable without every decoder installed | the application needs queries, indexes or transactions |
| a new domain format needs bounded streaming and integrity       | an existing domain format already owns those concerns  |

OBST does not provide a data model, query language, database or universal
compression strategy. It provides a stable representation layer under those
things.

## Try it in 20 seconds (I timed it! :D)

From a checkout:

```bash
git clone https://github.com/SmolBlackHole/Obst.git
cd Obst
python -m pip install .
python -m pip install ./plugins/defaults
obst plugins enable obst-defaults
obst inspect samples/apple.obst
```

Inspection validates the stored container without decoding the JPEG inside.
The enabled `obst-defaults` plugin adds the friendly file and zlib
interpretation:

```text
OBST container 0.2-apple
Streams                       1
Recipes                       1
Chunks                        6
Container size                260.6 KiB
Original size                 361.5 KiB (committed)
Integrity                     valid (terminal commit and encoded CRCs)
Required decoders available   yes
Logical recovery              not attempted
```

The matching source image, more sample containers and complete Unsplash
attribution live in [`samples/`](samples/). The toolchain can emit the same
inspection as JSON:

```bash
obst inspect samples/apple.obst --json
```

The defaults plugin also contributes portable-file packing and extraction:

```bash
obst pack apple.jpg banana.jpg -o fruit.obst
obst unpack fruit.obst -o restored
```

See the complete [human-readable](docs/toolchain/cli-output-reference.md) and
[JSON](docs/toolchain/cli-json-output-reference.md) output references for every
current command.

The Python project ships as 2 distributions. `obst` provides the runtime,
plugin manager, CLI host and native structural inspection. `obst-defaults`
provides replaceable first-party Extensions plus the `pack` and `unpack`
commands. Installing a plugin only makes it discoverable. Enabling, selecting
or explicitly testing it is the separate host decision that permits its code
to execute.

## How does the container work?

An OBST byte stream contains a manifest, independently framed chunks and a
terminal commit.

| Concept            | Role                                                      |
| ------------------ | --------------------------------------------------------- |
| Logical stream     | One ordered byte sequence with a versioned stream profile |
| Chunk              | One bounded and independently framed part of a stream     |
| Recipe             | The ordered Stage pipeline used to represent one chunk    |
| Extension contract | A stable identifier for stream or Stage behavior          |
| Terminal commit    | The final record binding the completed representation     |

A Recipe runs forward while encoding and backward while decoding:

```mermaid
flowchart LR
    Logical["Logical chunk"] --> Delta["obst.delta8@1"]
    Delta --> Zlib["obst.zlib@1"]
    Zlib --> Stored["Encoded payload"]
    Stored --> Inflate["inverse obst.zlib@1"]
    Inflate --> Undelta["inverse obst.delta8@1"]
    Undelta --> Recovered["Recovered chunk"]
```

The invariant is byte-exact:

```text
decode(encode(logical_bytes)) == logical_bytes
```

A Recipe may contain no Stages. That is the canonical identity
representation: stored bytes equal logical bytes and no Stage decoder is
required.

The manifest appears before the chunks, so a reader can inspect streams,
Recipes and Extension contracts before it sees any payload. Each chunk names
the Recipe it actually uses. Unknown Stages do not make the framing corrupt,
but affected chunks cannot be recovered locally.

The [anatomy guide](docs/anatomy.md) explains these relationships. Exact bytes,
field sizes and validity rules belong exclusively to the
[format specification](docs/format.md).

## Can I extend it?

Yes. `obst.bytes@1` is the one core stream contract. The shipped zlib, Delta8
and portable-file capabilities are ordinary Extensions from the separately
installed `obst-defaults` plugin. Third-party Extensions use the same registry
and provider contracts. There is no first-party VIP entrance.

Only Stage and stream-profile IDs enter container bytes. Carriers, packagers
and plugins are host-selected toolchain capabilities. Container bytes can
never install, enable or select executable code.

The encoder may be simple or absurdly sophisticated. It may use one fixed
Recipe or benchmark hundreds of candidates and consult the alignment of the
planets and stars. The container stores the winner, not the encoder's emotional
journey.

Start with the [Extension guide](docs/toolchain/extensions.md) for capability
boundaries and the [plugin guide](docs/toolchain/plugins.md) for installation,
activation and the trusted-code boundary.

## Status

OBST is experimental and under active development. The v0.2 conformance
vectors pin the current `0.2-apple` draft, but compatibility has not frozen.
Intentional pre-freeze wire changes regenerate the vectors and samples.

The reference runtime reads, writes and inspects bounded chunked containers.
The explicitly activated `obst-defaults` plugin supplies Delta8, zlib and
portable-file tooling without a privileged loading path.

What is still missing matters: preserved cross-language recovery, constrained
memory results, longer-running fuzzing, production tuning and real workload
benchmarks. The [roadmap](ROADMAP.md) tracks those decisions without pretending
the format is already battle tested.

## Documentation

The [documentation index](docs/README.md) routes readers by task. The shortest
paths are:

| Need                               | Start here                                         |
| ---------------------------------- | -------------------------------------------------- |
| Understand the container           | [Anatomy](docs/anatomy.md)                         |
| Implement or validate OBST bytes   | [Format specification](docs/format.md)             |
| Use the Python reference toolchain | [Toolchain guide](docs/toolchain/README.md)        |
| Use the CLI                        | [CLI guide](docs/toolchain/cli.md)                 |
| Write an Extension or plugin       | [Extension guide](docs/toolchain/extensions.md)    |
| Understand design decisions        | [Design notes](docs/design.md)                     |
| Run or publish conformance cases   | [Conformance guide](docs/toolchain/conformance.md) |
| Contribute code or documentation   | [Contributing guide](CONTRIBUTING.md)              |
| Report a security issue            | [Security policy](SECURITY.md)                     |

## Development

The reference implementation targets Python 3.14. Its runtime, defaults plugin
and Adaptive-Zlib example are checked with strict typing and separate tests.

```bash
python -m venv .venv

# Linux/macOS
. .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install -e ".[dev]" -e ./plugins/defaults -e ./examples/plugin_adaptive_zlib
obst plugins enable obst-defaults
python scripts/quality.py
```

The quality command runs Ruff security linting, formatting, isort, mypy strict,
Pyright strict, Vulture, REUSE and all 3 distribution-owned test suites. GitHub
Actions runs the same gate on Linux and Windows. A separate security workflow
runs Gitleaks, pip-audit and CodeQL. Contributions follow the
[contributing guide](CONTRIBUTING.md); security reports follow the private
process in the [security policy](SECURITY.md).

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

TSBO was not intentional. The bug was fixed but the fruit stayed. Why OBST?

Honestly, I have no idea. It was a placeholder, and it stuck.

## Spare a starfruit? ⭐ :D

If you've read this far, consider leaving a star on the repository.
It helps me see that people are interested in the project and gives me
another excuse to keep turning random things into fruit. Thank you! :D

## License

This is a multi-license repository. File-level SPDX metadata and `REUSE.toml`
are authoritative.

| Material                                                   | License                                              |
| ---------------------------------------------------------- | ---------------------------------------------------- |
| OBST format specification and normative contracts          | [CC BY 4.0](LICENSES/CC-BY-4.0.txt)                  |
| Reference implementation, tooling and general project docs | [MPL 2.0](LICENSES/MPL-2.0.txt)                      |
| Unsplash sample images and containers that embed them      | [Unsplash License](LICENSES/LicenseRef-Unsplash.txt) |

The [name-use policy](TRADEMARKS.md) permits truthful compatibility claims and
reserves official project identity. Citation metadata lives in
[`CITATION.cff`](CITATION.cff). Independently written Extensions may use
another license, but first-party wire-visible contracts must document how to
recover their logical bytes.
