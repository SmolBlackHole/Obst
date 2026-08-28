# OBST command-line guide

Parent: [Documentation index](README.md)

This page documents the CLI that exists. The
[roadmap](../ROADMAP.md) owns unfinished commands and delivery order.

The runtime CLI owns format inspection, plugin management, capability inventory
and help. Explicitly activated plugins may contribute additional commands. The
separately installed `obst-defaults` plugin maps ordinary files to and from the
`obst.file@1` stream profile through `pack` and `unpack`. That plugin is a
filesystem frontend, not the container boundary. The Python core reads and
writes binary streams, so the same serialized container may instead be held in
memory, stored as a database BLOB or transferred through another adapter.

## Table of contents

- [OBST command-line guide](#obst-command-line-guide)
	- [Table of contents](#table-of-contents)
	- [Install and identify the format](#install-and-identify-the-format)
	- [Manage plugins and inspect capabilities](#manage-plugins-and-inspect-capabilities)
	- [Inspect a container](#inspect-a-container)
		- [Inspect from stdin](#inspect-from-stdin)
		- [What inspection validates](#what-inspection-validates)
		- [Structural inspection](#structural-inspection)
		- [Machine-readable inspection](#machine-readable-inspection)
		- [Status-only inspection](#status-only-inspection)
	- [Terminal presentation](#terminal-presentation)
	- [Pack explicit files](#pack-explicit-files)
		- [Packing policy](#packing-policy)
		- [Portable filenames](#portable-filenames)
	- [Unpack every file](#unpack-every-file)
	- [Resource policy](#resource-policy)
	- [Black magic that already works](#black-magic-that-already-works)
	- [Exit codes and errors](#exit-codes-and-errors)
	- [Unsupported operations](#unsupported-operations)
	- [Built-in help](#built-in-help)

The runtime always provides `inspect`, `plugins`, `extensions` and `help`.
Activating `obst-defaults` adds `pack` and `unpack`:

| Command      | Purpose                                               | Reads stdin |
| ------------ | ----------------------------------------------------- | ----------- |
| `inspect`    | Validate and describe one OBST container              | Yes         |
| `pack`       | Store explicit regular files in one container         | No          |
| `unpack`     | Restore every file stream from a container            | No          |
| `plugins`    | List, enable, disable or test installed plugins       | No          |
| `extensions` | Report capabilities from enabled and one-shot plugins | No          |
| `help`       | Show general or command-specific help                 | No          |

Installation does not activate any plugin. The persisted host state may enable
`obst-defaults` and third-party plugins through the same manager. An available
command may also add one exact `--plugin` name to its operation without changing
that state. This cannot make a command from an inactive plugin appear, because
the host builds its command tree only from already enabled plugins. See
[Extension packages and plugin discovery](extensions/plugins.md) for the
factory contract and trust boundary.

Generic version output and help for native commands do not load contributed
command factories. Help for a contributed command necessarily loads the
persistently enabled command contribution that defines its parser.

## Install and identify the format

From a checkout, install the runtime and ask the CLI which wire-format
generation it reads and writes:

```console
pip install .
obst --version
obst inspect samples/apple.obst
```

```text
obst format 0.1-apple
```

This is the format identity, not the Python package release. `apple` is the
stable codename for format major version 0. Minor `0.x` revisions retain that
codename.

The 2 distributions are deliberately separate:

- `obst` supplies the `obst` import package, native inspection and the generic
  CLI host; and
- `obst-defaults` supplies first-party extensions plus `pack` and `unpack`.

Installing `obst-defaults` still does not activate it. Installation expands
what the host can discover, not what it trusts enough to execute.

> [!NOTE]
> **Reserved semantics:** An incompatible format major receives a new codename.

## Manage plugins and inspect capabilities

List inert installed metadata and activation state:

```console
obst plugins list
obst plugins list --json
```

This command does not import the referenced modules. It reports the canonical
plugin name, installation and enabled state, all contribution references,
distribution name and version, package summary and Documentation project URL.
A plugin has no wire contract and therefore no specification URL; each loaded
Extension owns its own descriptor and contract.

Change the persistent enabled set without loading plugin code:

```console
obst plugins enable obst-defaults
obst plugins disable obst-defaults
```

An absent state file means that no plugins are enabled. The first change writes
the complete enabled set to local configuration. `OBST_CONFIG_HOME` overrides
that directory. Invalid state fails explicitly instead of being silently
replaced.

Run the portable suite deliberately published by one installed Extension
plugin:

```console
obst plugins test obst-defaults
obst plugins test obst-defaults --json
obst plugins test example --plugin dependency
```

> [!WARNING]
> `obst plugins test` executes installed plugin code with your current process
> privileges. No sandbox is used. Test only plugins you trust.

Testing loads and executes that plugin's `obst.extensions` and
`obst.conformance` factories. Each `--plugin NAME` explicitly supplies a
dependency capability for this test only; no dependency is discovered or
enabled automatically. Testing does not enable any plugin. A failed case
returns exit code `11` after printing the complete report.

List capabilities from the enabled set plus optional one-shot additions:

```console
obst extensions
obst extensions --json
obst extensions --plugin example
```

The first-party `obst-defaults` plugin uses the same entry-point, activation,
factory and registry path as every third-party package. Each explicit
`--plugin NAME` adds its ordinary extension values to a fresh immutable
registry for that command only. It does not expose that plugin's own command
contributions. Container bytes never select, enable or load plugins.

These commands have schema-versioned JSON output. Plugin catalog schema `5`
reports all 3 contribution entry-point groups plus inert records with install,
enabled state, distribution metadata and factory provenance. Plugin
conformance report schema `2` reports each case ID, kind, optional Extension
ID, pass state and failure text. The static suite catalog itself uses schema
`1`. Cataloging never imports plugin code.
Extension inventory schema `3` reports loaded IDs, kinds and descriptors in 4
typed record shapes. Stage and stream-profile records expose their execution,
wire-codec and interpreter availability. Carrier records expose reader, writer
and publisher availability; packager records expose packaging availability.
Every Extension record uses the same optional `specification_url` field. For
Stages and stream profiles it can identify the portable contract copied into a
manifest. For runtime-only carriers and packagers it remains local registry
metadata. The inventory contains no executable provider objects.

## Inspect a container

```text
obst inspect [-h] [--json | --quiet] [--require-decodable] [--structural]
             [--plugin NAME] [INPUT]
```

`INPUT` is a path or `-` for stdin. Omitting it also reads stdin.
`inspect` belongs to the runtime and remains available without any installed or
enabled plugin. A path or stdin is adapted by the CLI frontend; the core
inspection operation still receives only a `BinaryReader`. Enabled plugins and
explicit `--plugin` selections enrich capability and interpretation reporting,
but do not make the command exist.

```console
obst inspect samples/apple.obst
obst inspect samples/apple.obst --json
obst inspect samples/apple.obst --quiet
obst inspect samples/apple.obst --require-decodable
obst inspect samples/apple.obst --structural
obst inspect data.obst --plugin example
```

### Inspect from stdin

On POSIX shells:

```console
obst inspect - --json < samples/apple.obst
```

On Windows, `cmd.exe` provides a binary-safe redirect, including when invoked
from Windows PowerShell 5.1:

```powershell
cmd /c "obst inspect - --json < samples\apple.obst"
```

Do not pipe a container through `Get-Content` in Windows PowerShell 5.1. Its
object pipeline can change arbitrary binary bytes before OBST receives them.

### What inspection validates

The [container anatomy](anatomy.md#the-pieces-at-a-glance) defines the manifest,
streams, recipes, chunks and stages named below.

Inspection consumes the complete container in one pass. The input does not
need to be seekable. It validates:

- the magic, format version and header flags
- manifest framing and manifest CRC
- stream, recipe and chunk references
- chunk sequence and stored payload lengths
- every encoded chunk CRC
- the absence of trailing or truncated container data

It deliberately does not run the decode pipelines. A successful inspection
therefore proves that the terminal commitment, container framing and encoded
payloads are intact, not that every decoded byte has been reconstructed. The
format-defined logical integrity field is verified only when its chunk is
decoded.

The human-readable summary includes:

- format version and codename
- stream, recipe and chunk counts
- complete container size
- committed original size and the container-to-original ratio
- stream IDs, types, chunk counts, recipe usage and per-stream payload sizes
- portable filenames for `obst.file@1` streams when its interpreter is enabled
- recipe stages, actual chunk counts and interpreted zlib levels where available
- declared recipe use and actual chunk use for every stage
- whether every stage required by an actual payload chunk has a local decoder
- missing required stages, without treating unused recipes as requirements
- local stage descriptions and declared specification URLs
- a compact resource footprint with manifest size, largest chunks, stage
  executions and largest materialized stream

Human output escapes terminal controls, line separators and Unicode
bidirectional controls as visible `\uXXXX` sequences. This applies to profile
labels, extension descriptions, paths and errors instead of trusting each
provider to sanitize its own text. Ordinary Unicode, including zero-width
joiners, remains unchanged.

The terminal record commits to the sum of declared logical chunk sizes. Those
sizes are checked against actual decoded output only when payloads are decoded,
for example by `unpack`.

The displayed compression ratio is `container_size / original_size`. It
includes the OBST header, manifest, chunk framing and terminal commit, not only
compressed payload bytes.

`Required decoders available` is derived from recipes referenced by actual
chunks. An unknown stage in an unused recipe remains visible but does not make
this result fail. Inspection does not run those decoders, so `Logical recovery`
remains `not attempted` even when every required decoder is available.

### Structural inspection

Ordinary human and JSON output may call metadata and parameter interpreters
from every activated Extension in the operation registry. These callbacks add
friendly fields but never replace raw metadata or stage-parameter bytes.

`--structural` disables every optional interpreter callback while retaining
framing validation, raw bytes, local descriptors and decoder-capability
reporting:

```console
obst inspect samples/apple.obst --json --structural
```

This mode is useful for hostile inputs, minimal tooling and distinguishing the
container parser from optional extension semantics. `--quiet` is also
callback-free because it renders no interpreted fields.

### Machine-readable inspection

`--json` emits schema version 6. It writes JSON only, without the ASCII apple.

| Field                         | Meaning                                                                   |
| ----------------------------- | ------------------------------------------------------------------------- |
| `schema_version`              | Inspection JSON schema, `6`                                               |
| `format`                      | Format name, major, minor, codename and display label                     |
| `streams`, `recipes`          | Manifest declaration counts                                               |
| `chunks`                      | Chunks observed and verified against the terminal commitment              |
| `container_size`              | Bytes read for the complete OBST container                                |
| `original_size`               | Committed sum of declared logical chunk sizes                             |
| `encoded_payload_size`        | Sum of encoded chunk payload sizes                                        |
| `container_to_original_ratio` | Container bytes divided by original bytes, or `null` for empty input data |
| `integrity`                   | Terminal, structural and encoded-payload validation result                |
| `required_decoders_available` | Whether stages used by actual chunks have local decoders                  |
| `missing_required_stages`     | Missing stages required by actual chunks                                  |
| `missing_declared_stages`     | All missing stages, including those declared only by unused recipes       |
| `logical_recovery`            | `not_attempted`, because inspection never decodes payloads                |
| `interpretation_policy`       | Extension IDs explicitly allowed to run optional interpreters             |
| `resource_footprint`          | Exact structural resource facts observed during inspection                |
| `stage_details`               | Decoder availability plus declared and local stage metadata               |
| `stream_details`              | Raw metadata, optional interpretation, recipe usage, counts and sizes     |
| `recipe_details`              | Raw stage parameters, optional interpretation and actual chunk count      |

Each `stage_details` entry distinguishes `declared_recipe_ids`,
`used_recipe_ids` and `used_chunks_by_recipe`. It also contains `required`,
`decoder_available`, `declared_specification_url`, `display_name`, `summary`
and `local_specification_url`.

`resource_footprint` includes declaration counts, manifest and container
sizes, largest encoded and logical chunks, logical totals, required stage
executions and the largest stream size relevant to full materialization. It
does not claim peak memory, CPU time or intermediate decoder sizes.
Declared URLs come from the untrusted manifest; local fields come from the
registered `ExtensionDescriptor`. Inspection displays them but does not fetch
either URL or load provider code.

For first-party containers, declared and local URLs normally match because the
packer copied the same registered descriptor that the CLI registers for
inspection. A mismatch is still displayed rather than silently resolved. See
[Container inspection](core/inspection.md) for the complete provenance model.

`stream_details.metadata_hex` and every stage's `parameters_hex` are the raw,
authoritative bytes. Interpreter output is optional additional meaning. An
unknown or invalid interpretation never replaces those bytes.
`interpretation_policy.extension_ids` records the exact callback allowlist used
for this report. It is empty for `--structural` and `--quiet` inspection.

> [!NOTE]
> **Reserved semantics:** Consumers check `schema_version`. An incompatible
> inspection shape receives a new schema version instead of silently changing
> the existing one.

### Status-only inspection

`--quiet` suppresses the inspection summary and skips optional interpreter
callbacks. Use it when the exit code is the primary result:

```console
obst inspect samples/apple.obst --quiet
```

`--json` and `--quiet` are mutually exclusive.

Invalid input, corruption and I/O failures still write their diagnostic to
stderr. A missing stage combined with `--require-decodable` is a status result,
so that particular exit-code 4 path remains silent in quiet mode.

By default, a structurally valid container with an unknown stage still exits
successfully because it remains inspectable. Add `--require-decodable` to make
that condition fail with exit code 4. This works with the human, JSON and quiet
modes.

## Terminal presentation

Human output uses aligned fields, separated sections and restrained color when
stdout or stderr is an interactive terminal. Redirected output remains plain
UTF-8 text, and JSON output never contains ANSI control sequences. The runtime
emits standard terminal color sequences directly and gains no presentation-only
package dependency.

Set `NO_COLOR` to disable color. Set a non-empty `FORCE_COLOR` value other than
`0` to retain color when a terminal cannot be detected. `NO_COLOR` wins when
both are present. Untrusted names, labels and error details are escaped before
presentation codes are added.

## Pack explicit files

```text
obst pack [-h] -o OUTPUT [--plugin NAME] INPUT [INPUT ...]
```

Every positional `INPUT` is an existing regular file. `-o` or `--output`
explicitly names the new container, so the destination cannot be mistaken for
another input:

```console
obst pack samples/apple.obst -o samples/apple-container.obst
obst pack samples/apple.obst samples/fruit-bowl.obst samples/pineapple.obst -o all-fruit.obst
```

`--plugin NAME` is a one-shot capability addition for this already available
command. The current packing policy requires a file-source and file-materializer capability under
`obst.file@1`, plus parameter authoring and encoding under `obst.zlib@1`.
Concrete Python classes and the plugins that supplied them are irrelevant.
All capabilities are resolved before the output carrier publishes a target.

The second example is valid OBST inside OBST. The inner containers are stored
as ordinary file bytes. `pack` does not open, tune or recursively rewrite them.
Unpacking restores those inner `.obst` files byte for byte.

### Packing policy

- one `obst.file@1` stream is created per input, in CLI argument order
- stream IDs start at 0
- the portable basename is stored, not the source directory
- every stream uses `obst.zlib@1` at level 9
- input is read in logical chunks of 64 KiB, not loaded as one large byte string
- an empty file becomes a valid stream with zero chunks
- only regular, non-redirected files are accepted
- an existing output is never overwritten
- the complete temporary container is synced before exclusive publication

The [file-extension guide](extensions/files.md#create-logical-stream-sources)
owns source-handle and portable-name rules. The
[filesystem carrier](extensions/carriers/filesystem.md#publish-a-new-container)
owns hard-link publication, cleanup receipts and filesystem limitations.

`pack` does not accept `-` or stdin. Chunked file reading is streaming
internally, but it is not a stdin interface.

### Portable filenames

Every member uses the portable basename contract from the
[`obst.file@1` profile](contracts/streams/file.md). Packing rejects unsafe names
and collisions before creating the output.

On success, the command reports every member's logical size and chunk count:

```text
Packed 2 files
  Destination     fruits.obst
  Container size  123 B

Files
  apple.txt          3 B  1 chunk
  banana.bin        64 B  1 chunk
```

## Unpack every file

```text
obst unpack [-h] -o OUTPUT_DIRECTORY [--plugin NAME] INPUT
```

`-o` and `--output` explicitly name the extraction directory. The option is
required, so extraction never silently targets the working directory.

```console
obst unpack fruits.obst -o restored
obst unpack fruits.obst --output restored
```

`unpack` accepts a path only, not stdin. It extracts every stream for which the
activated Extension set supplies a `FileMaterializer` under the exact declared
stream type. Mixed file profiles are valid; one missing materializer rejects
the complete request before output creation rather than guessing at semantics.

Before decoding, OBST validates every member name, collision and destination.
It decodes into temporary storage, verifies every chunk and publishes only
regular files without overwriting existing targets. Extraction never executes,
imports or launches recovered bytes. The output may still be executable if
another program launches it later.

The complete extraction, rollback, redirected-root and threat-model guarantees
live in the [file-extension guide](extensions/files.md#extract-files). The
[`obst.file@1` contract](contracts/streams/file.md) lists metadata that is not
preserved.

On Windows, an input container may carry Mark of the Web in the NTFS
`Zone.Identifier` stream. Extracted files do not inherit that origin. When the
CLI detects the mark it exits successfully but writes an explicit warning:

```text
obst: warning: input has Windows Mark of the Web; extracted files do not inherit it and may be treated as local files
```

Library callers own equivalent origin or quarantine policy for their carrier
context. `unpack` always restores all members. An explicitly selected plugin
may supply a decoder or file materializer required by the request; it does not
cause container-directed discovery.

On success, the command lists the restored basenames:

```text
Unpacked 2 files
  Destination     restored

Files
  apple.txt
  banana.bin
```

## Resource policy

The CLI uses the finite `DEFAULT_RESOURCE_LIMITS` core policy. File extraction
also uses `DEFAULT_FILE_EXTRACTION_LIMITS`, which bounds member count, one
recovered file and total recovered filesystem bytes.

The command line does not expose a matrix of limit flags. Library callers that
need deployment-specific ceilings pass `ResourceLimits` and
`FileExtractionLimits` explicitly. Crossing a local ceiling reports
`obst: resource_limit: ...` and returns exit code `10`; it does not label the
container corrupt or invalid.

The complete defaults and accounting scopes live in the
[resource guide](core/resources.md).

## Black magic that already works

The format is small, but a few pleasantly suspicious things are real:

- inspect a non-seekable OBST stream from stdin while validating its stored form
- preserve an unknown stream type as bytes when its pipeline stages are available
- inspect a structurally valid container even when a decoder stage is missing
- carry several named files as independent, chunked streams in one container
- store OBST inside OBST and recover the inner container bit for bit
- report declared original size and framing-inclusive compression ratio without decoding
- preserve empty files and normalized Unicode filenames
- drive tooling through JSON or exit codes without inviting the ASCII apple

The recursion is composition, not recursive interpretation. The
container is not secretly opening its own containers in the night.

## Exit codes and errors

Errors use `obst: KIND: MESSAGE` on stderr. Text output is configured as UTF-8
when the Python stream supports reconfiguration. Dynamic diagnostic text uses
the same terminal-safe escaping as the human inspection report.

The [runtime error reference](errors.md) owns the complete exit-code table,
Python exception hierarchy and negative examples.

## Unsupported operations

The reference CLI does not provide:

- stdin input for `pack` or `unpack`
- selecting one stream or member during inspection or extraction
- nested inspection of an inner OBST member
- indexed or random-access reads
- autotuned recipe selection in the production packager
- recursive or cross-stream repacking
- directory-tree and filesystem-metadata profiles

## Built-in help

```console
obst help
obst help inspect
obst help pack
obst help unpack
obst help plugins
obst help extensions
```

`pack`, `unpack` and any other contributed topic appear only while the plugin
that contributes the corresponding command is enabled.

`obst help plugins` lists the `list`, `enable`, `disable` and `test`
subcommands. Each subcommand also supports conventional `-h` and `--help`.

The conventional `-h` and `--help` flags remain available, for example
`obst inspect --help`. `obst help COMMAND` is the easier-to-discover spelling;
both render the same parser-owned command help. The installed command output is
the final authority for that build.
