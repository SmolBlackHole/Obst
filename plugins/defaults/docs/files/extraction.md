# Extract files

Parent: [Portable files](README.md)

`FileArchiver.extract()` restores every compatible logical stream through the
materializer registered for its exact stream-profile ID. This page owns the
Defaults adapter's filesystem validation, extraction budgets and publication
failure behavior.

## Table of contents

- [Extract files](#extract-files)
	- [Table of contents](#table-of-contents)
	- [Run extraction](#run-extraction)
		- [Rejected requests](#rejected-requests)
	- [Resource accounting](#resource-accounting)
	- [Results and publication failures](#results-and-publication-failures)

## Run extraction

`extract()` accepts a structural `ContainerReader`, an output directory and
the operation's `ResourceAccounting`. Stage decoding uses the registry already
owned by the archiver:

```python
from io import BytesIO
from pathlib import Path

from obst.core import ContainerReader, CoreResource, ResourceAccounting
from obst.resources import LimitProfile, ResourcePolicy
from obst_defaults.files import FileResource

policy = ResourcePolicy(
    tuple(CoreResource) + tuple(FileResource),
    LimitProfile(
        "local-extraction",
        "Accept at most 100 file members.",
        ((FileResource.ARCHIVE_MEMBERS, 100),),
    ),
)
accounting = ResourceAccounting(policy)
reader = ContainerReader(BytesIO(container_bytes), accounting=accounting)
result = archiver.extract(
    reader,
    Path("restored"),
    accounting=accounting,
)
```

Every declared stream must have one active `FileMaterializer` under its exact
stream type. A container may therefore mix `obst.file@1`, a future
`obst.file@2` and third-party file profiles. The adapter validates all plans,
portable collisions and existing targets before decoding. It then decodes
chunks sequentially into temporary files and publishes complete members
through hard links. An existing target is never overwritten.

The selected output root must be a regular directory, not a symbolic link or
Windows reparse point. The adapter records its filesystem identity and checks
that identity again before final publication. It creates only regular files;
member bytes are never imported, launched, dispatched to a shell or handed to
an operating-system file association.

Container framing, chunk integrity, Stage execution and file extraction use the
same [resource policy](../../../../docs/core/resources.md). No second
file-specific policy object exists.

### Rejected requests

The file adapter validates the member set before decoding or publishing any
final member:

| Input or destination                                   | Result                                                          |
| ------------------------------------------------------ | --------------------------------------------------------------- |
| metadata name `../outside.bin`                         | `FileProfileError`; the profile does not accept the metadata    |
| metadata contains `U+202E`                             | `FileProfileError`; the first-party profile rejects the control |
| local name contains a surrogate code point             | `FileProfileError`; it cannot become canonical UTF-8 metadata   |
| stream has no active file materializer                 | `FileArchiveError` before the output directory is created       |
| members `Fruit.txt` and `fruit.TXT`                    | `FileArchiveError`; portable comparison finds a duplicate       |
| source is a symlink or reparse point                   | `FileProfileError`; no source handle is exposed                 |
| output root is a symlink or reparse point              | `FileArchiveError`; no member is decoded or published           |
| target path already exists                             | `FileArchiveError`; existing bytes remain untouched             |
| member count exceeds `obst.file@1/archive_members`     | `ResourceLimitError` before the output directory is created     |
| one member exceeds `obst.file@1/archive_member_bytes`  | `ResourceLimitError`; no final member is published              |
| total output exceeds `obst.file@1/archive_total_bytes` | `ResourceLimitError`; temporary output is cleaned up            |

Each materializer returns a `FileMaterialization`, not a filesystem path or an
open handle. The archiver revalidates its basename before joining it with the
output directory. A stream profile cannot use metadata to request a directory,
path traversal, alternate data stream or arbitrary write target.

This path-based cross-platform adapter is safe for ordinary caller-owned
directories. It is not a privilege boundary for an output tree another actor
can replace concurrently. Such deployments need platform-specific
directory-handle and no-follow operations around the adapter.

These failures use the families defined in the [plugin error
reference](../errors.md). They are not evidence that the container framing or
payload CRC is corrupt.

## Resource accounting

`obst-defaults` publishes these typed resources through its ordinary
`obst.resources` contribution:

| Resource ID                        | Measures                     | Default |
| ---------------------------------- | ---------------------------- | ------: |
| `obst.file@1/archive_members`      | Members in one extraction    |   4,096 |
| `obst.file@1/archive_member_bytes` | Logical bytes in one member  |   4 GiB |
| `obst.file@1/archive_total_bytes`  | Logical bytes in all members |  16 GiB |

The resources become available only when the plugin is active. The host may
override them in the same `LimitProfile` as Core resources, including an
explicit `None` that disables one ceiling. Member count is checked before the
output directory or any temporary file is created. Per-member and total bytes
are charged from declared logical chunk sizes before decoding and writing. A
refusal raises `ResourceLimitError` and publishes no final member files.

Extraction streams chunks to temporary files, so it does not materialize a
complete logical stream and does not consume
`materialized_stream_bytes`. The reader's container, chunk, logical-byte and
Stage-execution resources still apply.

## Results and publication failures

Successful extraction returns `FileExtractionResult` with:

- `output_directory`, the requested destination;
- `paths`, the final member paths in manifest stream order; and
- `cleanup_issues`, residual temporary resources that could not be removed
  after all final members were published.

The member set is not one filesystem transaction. If publication fails after
some hard links were created, the adapter attempts to remove those published
members and attaches cleanup failures to the primary exception. The output
directory itself may remain after a failed operation.

Origin and quarantine metadata belong to the caller or Carrier context, not
to `obst.file@1`. The archiver never invents or copies member-controlled
extended attributes. The [command-line guide](../cli.md#unpack-every-file)
owns the Windows warning shown for input containers carrying
`Zone.Identifier`.
