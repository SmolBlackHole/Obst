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
	- [Extraction limits](#extraction-limits)
	- [Results and publication failures](#results-and-publication-failures)

## Run extraction

`extract()` accepts a structural `ContainerReader`, an output directory and
filesystem-specific limits. Stage decoding uses the registry already owned by
the archiver:

```python
from io import BytesIO
from pathlib import Path

from obst.core import ContainerReader
from obst_defaults.files import FileExtractionLimits

reader = ContainerReader(BytesIO(container_bytes))
result = archiver.extract(
    reader,
    Path("restored"),
    limits=FileExtractionLimits(max_members=100),
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

Container framing, chunk integrity and Stage execution retain the
[`ResourceLimits`](../../../../docs/core/resources.md) attached to
`ContainerReader`. `FileExtractionLimits` covers only the additional resources
created by filesystem extraction.

### Rejected requests

The file adapter validates the member set before decoding or publishing any
final member:

| Input or destination                       | Result                                                          |
| ------------------------------------------ | --------------------------------------------------------------- |
| metadata name `../outside.bin`             | `FileProfileError`; the profile does not accept the metadata    |
| metadata contains `U+202E`                 | `FileProfileError`; the first-party profile rejects the control |
| local name contains a surrogate code point | `FileProfileError`; it cannot become canonical UTF-8 metadata   |
| stream has no active file materializer     | `FileArchiveError` before the output directory is created       |
| members `Fruit.txt` and `fruit.TXT`        | `FileArchiveError`; portable comparison finds a duplicate       |
| source is a symlink or reparse point       | `FileProfileError`; no source handle is exposed                 |
| output root is a symlink or reparse point  | `FileArchiveError`; no member is decoded or published           |
| target path already exists                 | `FileArchiveError`; existing bytes remain untouched             |
| member count exceeds `max_members`         | `ResourceLimitError` before the output directory is created     |
| one member exceeds `max_member_bytes`      | `ResourceLimitError`; no final member is published              |
| total output exceeds `max_total_bytes`     | `ResourceLimitError`; temporary output is cleaned up            |

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

## Extraction limits

The default extraction policy is:

```python
from obst_defaults.files import FileExtractionLimits

limits = FileExtractionLimits(
    max_members=4_096,
    max_member_bytes=4 * 1024**3,
    max_total_bytes=16 * 1024**3,
)
```

Each field accepts a non-negative integer or an explicit `None` that disables
only that ceiling. Member count is checked before the output directory or any
temporary file is created. Per-member and total bytes are charged from
declared logical chunk sizes before decoding and writing. A refusal raises
`ResourceLimitError` and publishes no final member files.

Extraction streams chunks to temporary files, so it does not materialize a
complete logical stream and does not consume
`max_materialized_stream_bytes`. The reader's container, chunk, logical-byte
and Stage-execution limits still apply.

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
