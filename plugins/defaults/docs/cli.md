# obst-defaults command-line guide

Parent: [obst-defaults documentation](README.md)

The activated `obst-defaults` plugin contributes `pack` and `unpack` to the
ordinary OBST command host. Without this plugin, those commands are absent.

## Table of contents

- [obst-defaults command-line guide](#obst-defaults-command-line-guide)
	- [Table of contents](#table-of-contents)
	- [Activate the plugin](#activate-the-plugin)
	- [Pack explicit files](#pack-explicit-files)
	- [Unpack every file](#unpack-every-file)
	- [Machine-readable results](#machine-readable-results)
	- [Resource accounting](#resource-accounting)
	- [Unsupported operations](#unsupported-operations)

## Activate the plugin

```console
python -m pip install ./plugins/defaults
obst plugins enable obst-defaults
obst help
```

Installation only makes the contribution discoverable. Persistent enablement
is required before the contributed `pack` and `unpack` parsers exist. A
one-shot `--plugin NAME` can add capabilities to one of those already available
commands, but cannot make an inactive command contribution appear. The generic
[plugin guide](../../../docs/extensions/plugins.md) owns that loading and trust
boundary.

## Pack explicit files

```text
obst pack [-h] -o OUTPUT [--plugin NAME] [--json] INPUT [INPUT ...]
```

Every positional `INPUT` is an existing regular file. `-o` or `--output`
explicitly names the new container:

```console
obst pack samples/apple.obst -o samples/apple-container.obst
obst pack samples/apple.obst samples/fruit-bowl.obst samples/pineapple.obst -o all-fruit.obst
```

The command resolves `obst.file@1`, `obst.zlib@1`, `obst.filesystem@1` and
`obst.fixed@1` by capability ID from the operation's immutable registry. It
creates one stream per input in argument order, uses zlib level 9 and requests
exclusive filesystem publication without overwriting an existing target.

The [file-source guide](files/sourcing.md#create-logical-stream-sources) owns
handle validation, portable metadata, empty-file behavior and the default
logical chunk size. The [filesystem Carrier](carriers/filesystem.md#visibility-and-durability)
owns temporary output, synchronization and exclusive publication.

`pack` does not accept stdin. Nested `.obst` inputs remain ordinary logical
file bytes and are not opened or recursively rewritten.

## Unpack every file

```text
obst unpack [-h] -o OUTPUT_DIRECTORY [--plugin NAME] [--json] INPUT
```

The destination is always explicit. The command extracts every stream for
which the active registry supplies a file materializer under the exact stream
type declared by the container. One missing materializer rejects the complete
request before output creation.

Names, collisions and destinations are validated before decoding. Recovery
uses temporary storage, verifies chunk integrity and publishes only regular
files without overwriting existing targets. It never executes, imports or
launches recovered bytes. The [extraction guide](files/extraction.md) owns the
complete validation, limit, rollback and filesystem threat model.

On Windows, extracted files do not inherit an input container's NTFS
`Zone.Identifier`. When detected, the command succeeds but warns that the
recovered files may be treated as local files.

## Machine-readable results

Both commands accept `--json`. Successful output contains only one
schema-versioned JSON document on stdout. Diagnostics and cleanup warnings
remain on stderr, so stdout stays parseable.

Pack schema `1` reports `destination`, exact `container_size`, one `files`
record per input and any `cleanup_issues`. Each file record contains its
portable `name`, exact `logical_size` and `chunks` count.

Unpack schema `1` reports `destination`, every restored file's `name` and
complete `path`, `cleanup_issues` and `windows_origin_not_propagated`. The
last field records the same successful Windows-origin warning described above.

## Resource accounting

The command host supplies one operation-local `ResourceAccounting` to Pack,
Unpack and every nested operation. `obst-defaults` contributes its file-member
resources through `obst.resources`; it does not maintain a second extraction
policy or select a profile when the plugin is enabled. Use the native
[`obst limits`](../../../docs/cli.md#resource-limit-profiles) commands to create,
inspect and select local overrides.

Crossing a local ceiling reports `resource_limit` rather than calling valid
wire data corrupt. The core [resource guide](../../../docs/core/resources.md)
owns operation-wide accounting, while [file extraction](files/extraction.md#resource-accounting)
owns the adapter-specific ceilings.

## Unsupported operations

These contributed commands do not support stdin, selecting one member,
directory trees, filesystem metadata profiles, recursive repacking or
autotuned Recipe selection.

See [plugin-owned errors](errors.md) for the contributed exit codes and the
root [CLI guide](../../../docs/cli.md) for the command host, native inspection
and terminal behavior.
