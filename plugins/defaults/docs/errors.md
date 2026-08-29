# obst-defaults errors

Parent: [obst-defaults documentation](README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

The plugin owns file-profile, archive and Carrier failures raised by its
providers and maps them to contributed CLI error families. Core container and
plugin-manager errors remain documented by the OBST runtime.

## Table of contents

- [obst-defaults errors](#obst-defaults-errors)
	- [Table of contents](#table-of-contents)
	- [Python exceptions](#python-exceptions)
	- [Command failures](#command-failures)
	- [Negative examples](#negative-examples)
	- [Related errors](#related-errors)

## Python exceptions

| Exception           | Meaning                                                                                                  |
| ------------------- | -------------------------------------------------------------------------------------------------------- |
| `FileProfileError`  | File metadata, a selected source profile or reconstructed file bytes violate the concrete file contract. |
| `FileArchiveError`  | File-adapter composition or publication policy cannot map the selected streams to files.                 |
| `CarrierError`      | A Defaults Carrier cannot open, read, write, finish, commit, abort or publish safely.                    |
| `CarrierStateError` | A Defaults Carrier lifecycle operation is invoked in the wrong state.                                    |

All four inherit from the public runtime `ObstError` so callers can choose a
broad or precise catch boundary.

## Command failures

The plugin's commands contribute these exit codes through `CliCommandError`:

| Code | Error kind      | Meaning                                                         |
| ---- | --------------- | --------------------------------------------------------------- |
| `7`  | `archive_error` | File-adapter composition, name, target or materializer failure. |
| `8`  | `carrier_error` | Whole-container endpoint or publication failure.                |
| `9`  | `profile_error` | File metadata, member validation or reconstruction failure.     |

Core command-host failures such as invalid container input, I/O, resource
limits and plugin loading retain their root-defined exit codes.

## Negative examples

If `output.obst` already exists:

```console
$ obst pack input.bin -o output.obst
obst: carrier_error: output already exists: output.obst
```

The destination is not overwritten. This says nothing about the validity of
the input bytes or the selected Recipe.

Likewise, a missing materializer is an `archive_error`, not evidence that the
container framing is invalid. The host may activate a trusted plugin that
supplies the exact declared file-profile capability and retry from a new
operation.

## Related errors

The root [runtime error reference](../../../docs/toolchain/errors.md) owns core
exceptions, provider rejection boundaries, native CLI errors and the generic
diagnostic format.
