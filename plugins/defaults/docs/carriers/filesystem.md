# Filesystem carrier: `obst.filesystem@1`

Parent: [obst-defaults Carriers](README.md)

The filesystem carrier binds OBST container bytes to one caller-selected path.
It can read an existing container or publish a newly completed container
transactionally. Paths, overwrite policy and filesystem guarantees remain
runtime concerns and never enter the OBST byte stream.

## Table of contents

- [Filesystem carrier: `obst.filesystem@1`](#filesystem-carrier-obstfilesystem1)
	- [Table of contents](#table-of-contents)
	- [Capabilities](#capabilities)
	- [Read an existing container](#read-an-existing-container)
	- [Publish a new container](#publish-a-new-container)
	- [Visibility and durability](#visibility-and-durability)
	- [Failure semantics](#failure-semantics)

## Capabilities

| Property          | Value                                                          |
| ----------------- | -------------------------------------------------------------- |
| Extension ID      | `obst.filesystem@1`                                            |
| Extension kind    | Carrier                                                        |
| Reader            | Yes                                                            |
| Streaming writer  | No                                                             |
| Publisher         | Yes                                                            |
| Request types     | `FilesystemReadRequest`, `FilesystemPublishRequest`            |
| Publication value | `PublicationReceipt[Path]`                                     |
| Python provider   | `obst_defaults.carriers.filesystem.FilesystemCarrierExtension` |

The ID identifies a local runtime capability. It is not serialized into a
manifest and cannot be selected by container bytes.

## Read an existing container

```python
from pathlib import Path

from obst_defaults.carriers.filesystem import (
    FilesystemCarrierExtension,
    FilesystemReadRequest,
)

filesystem = FilesystemCarrierExtension()
session = filesystem.bind_reader(FilesystemReadRequest(Path("input.obst")))
source = session.open()
try:
    # Pass source to ContainerReader or inspect_container.
    ...
finally:
    session.close()
```

The session opens the path once and returns that same binary handle. Opening or
closing failures are reported as `CarrierError`. The core sees a
[`BinaryReader`](../../../../docs/core/reading.md), not the path.

## Publish a new container

```python
from pathlib import Path

from obst_defaults.carriers.filesystem import (
    FilesystemCarrierExtension,
    FilesystemPublishRequest,
)

filesystem = FilesystemCarrierExtension()
publisher = filesystem.bind_publisher(
    FilesystemPublishRequest(Path("output.obst"), overwrite=False)
)
```

The publisher creates a temporary sibling and exposes the final path only from
`commit()`. Packaging code writes through the returned `BinaryWriter` without
learning the destination path. The plugin's [package-execution
helper](package-execution.md#publish-transactionally) runs a prepared package
operation inside that transaction.

## Visibility and durability

Before publication, the carrier flushes and syncs the complete temporary file.
With overwrite enabled it publishes through `os.replace()`. Without overwrite
it hard-links the completed temporary file to the final name, so an existing
target wins the race and is never replaced.

This promises complete-file visibility, not universal crash durability. Parent
directory persistence depends on the operating system and filesystem. A
filesystem without the required hard-link semantics rejects no-overwrite
publication instead of copying progressively through the final name.

These guarantees assume a caller-owned destination directory. The carrier is
not a portable privilege boundary against another actor concurrently renaming
or mutating that directory tree. Supporting that stronger threat model would
require platform-specific directory handles and no-follow publication rather
than additional pathname checks in the shared carrier contract.

## Failure semantics

- A failure before publication triggers cleanup of unpublished state.
- `commit()` succeeds only after the final path is visible.
- Cleanup that fails after successful publication is returned in
  `PublicationReceipt.cleanup_issues`.
- Repeating an invalid lifecycle operation raises `CarrierStateError`.
- Existing output is refused unless the request explicitly enables overwrite.

The general [carrier lifecycle](../../../../docs/extensions/carriers.md#writer-and-publisher-semantics)
defines how these outcomes compose with packaging failures.
