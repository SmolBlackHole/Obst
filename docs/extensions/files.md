# Portable files

Parent: [Extension system](README.md)

The first-party file feature maps explicit regular files to portable
`obst.file@1` logical streams and restores those streams to a filesystem. This
page owns the Python file-capability protocols and `FileArchiver` composition.
The [stream contract](../contracts/streams/file.md) owns the wire-visible
basename and logical-byte rules for the first-party profile.

## Table of contents

- [Portable files](#portable-files)
	- [Table of contents](#table-of-contents)
	- [Composition boundary](#composition-boundary)
	- [Compose file capabilities](#compose-file-capabilities)
	- [Implement another file profile](#implement-another-file-profile)
	- [Create logical stream sources](#create-logical-stream-sources)
	- [Package files](#package-files)
	- [Extract files](#extract-files)
		- [Rejected file requests](#rejected-file-requests)
	- [File extraction limits](#file-extraction-limits)
	- [Results and publication failures](#results-and-publication-failures)
	- [Related documentation](#related-documentation)

## Composition boundary

`obst_defaults.files` exposes one cohesive first-party feature:

- `FileExtension` owns the self-describing `obst.file@1` extension identity,
  the typed `PortableFileMetadata` codec, optional metadata interpretation and
  both directional file capabilities;
- `FileSourceProfile` identifies a stream profile that can author one logical
  stream from a regular file name;
- `FileMaterializer` identifies a stream profile that can plan one safe regular
  file from recovered logical bytes and metadata;
- `FileArchiver.open_sources()` opens explicit regular files once and exposes
  bounded `LogicalStreamSource` values for that context lifetime; and
- `FileArchiver.extract()` selects a materializer by each stream's exact type
  ID, validates every plan, decodes and publishes without overwriting targets.

The caller still owns the registry, Recipe, packager, carrier, resource policy
and publication lifecycle. `FileArchiver` receives one immutable registry and
never discovers plugins or chooses hidden codec policy. The general
[application-adapter guide](archivers.md#compose-an-adapter) owns that flow.

For one Extension ID there may be at most one file-source provider and one
file-materializer provider. Complementary providers may be separate objects;
duplicates for the same capability are rejected.

## Compose file capabilities

Create one registry, then give that same snapshot to the file adapter and core
operations:

```python
from obst.core import ExtensionRegistry, RecipeSpec, StageSpec
from obst_defaults.carriers.memory import MemoryCarrierExtension
from obst_defaults.codecs import RawExtension
from obst_defaults.files import (
    FileArchiver,
    FileExtension,
    PortableFileMetadata,
)
from obst_defaults.packagers import FixedPackagerExtension

raw = RawExtension()
files = FileExtension()
memory = MemoryCarrierExtension()
fixed = FixedPackagerExtension()
recipe = RecipeSpec((StageSpec(raw.extension_id),))
registry = ExtensionRegistry((raw, files, memory, fixed))
archiver = FileArchiver(registry)

assert archiver.can_source(files.extension_id)
assert archiver.can_materialize(files.extension_id)

metadata = files.encode_metadata(PortableFileMetadata("apple.txt"))
assert files.decode_metadata(metadata) == PortableFileMetadata("apple.txt")
```

Registry construction validates identities, descriptors and core capabilities
once. `FileArchiver` then freezes its adapter-specific lookup from those same
captured contributions. The recipe is not bound to the archiver. Packing
supplies a source profile ID and recipe per request; extraction uses the stream
type and recipe IDs already declared by the container.

The generic metadata codec and the file capabilities serve different callers.
`encode_metadata()` and `decode_metadata()` expose the versioned metadata
contract. `encode_file_name()` and `plan_file()` additionally promise that the
profile can participate in the regular-file adapter.

## Implement another file profile

File capabilities are structural protocols. A third-party profile implements
only the directions it can support. This example can both author and restore
one named package file whose logical bytes remain the exact package bytes:

```python
from obst.core import ExtensionDescriptor, ExtensionKind
from obst_defaults.files import FileMaterialization


class PackageFileExtension:
    extension_id = "org.example/package-file@1"
    kind = ExtensionKind.STREAM_PROFILE
    descriptor = ExtensionDescriptor(
        display_name="Example package file",
        specification_url="https://example.org/obst/package-file-v1",
    )

    def encode_file_name(self, name: str, /) -> bytes:
        return name.encode("utf-8")

    def plan_file(self, metadata: bytes, /) -> FileMaterialization:
        return FileMaterialization(metadata.decode("utf-8"))
```

An extraction-only compatibility package may provide only `plan_file()`. A
source-only author may provide only `encode_file_name()`. If another activated
object already provides that same direction under the same ID, composition
fails instead of choosing one by load order.

## Create logical stream sources

`open_sources()` is a context manager over a non-empty sequence of `Path`
values. On entry it rejects symbolic links, Windows reparse points,
non-regular files, invalid portable basenames and case-folded duplicate
basenames. Each accepted file is opened once, validated from that handle and
becomes one stream under the explicitly selected source profile and recipe.

```python
from pathlib import Path

with archiver.open_sources(
    (Path("apple.jpg"), Path("measurements.bin")),
    source_profile_id=files.extension_id,
    recipe=recipe,
    chunk_size=64 * 1024,
) as sources:
    ...
```

File contents remain lazy, but path resolution does not. The packager reads
each source from the exact handle opened when the context was entered; it never
reopens the pathname. Leaving the context closes every handle, including after
packaging failure. One close failure never prevents the remaining handles from
being closed. An active packaging error stays primary and receives cleanup
failures as notes; after a successful body, the first close failure is raised
and later failures become notes. This binds identity, not a frozen snapshot:
another process that can write through the same file object may still change
bytes while OBST reads it.

The default chunk size is 64 KiB; an explicit chunk size must be a positive
integer. Each source declares the selected size as its maximum logical chunk
size.

## Package files

Packaging keeps every owner visible. The archiver and packager use the same
immutable registry:

```python
from obst_defaults.carriers import publish_package
from obst_defaults.carriers.memory import MemoryPublishRequest
from obst_defaults.packagers import FixedPackageRequest

with archiver.open_sources(
    (Path("apple.jpg"), Path("measurements.bin")),
    source_profile_id=files.extension_id,
    recipe=recipe,
) as sources:
    operation = registry.require_packager_provider(
        fixed.extension_id
    ).prepare_package(
        FixedPackageRequest(registry=registry, sources=sources)
    )
    publisher = registry.require_carrier_publisher_provider(
        memory.extension_id
    ).bind_publisher(
        MemoryPublishRequest()
    )
    published = publish_package(operation, publisher)
container_bytes = published.publication.reference
```

Selecting another carrier provider changes where the completed container is
published. Selecting another packager provider changes packaging policy.
Replacing the supplied recipe changes how chunks are represented. Replacing
the explicitly selected source profile changes the stream contract; none of
those choices changes the core container API.

## Extract files

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

Container framing, chunk integrity and stage execution retain the
[`ResourceLimits`](../core/resources.md) attached to `ContainerReader`.
`FileExtractionLimits` covers only the additional resources created by
filesystem extraction.

### Rejected file requests

The file adapter validates the member set before decoding or publishing any
final member:

| Input or destination                      | Result                                                          |
| ----------------------------------------- | --------------------------------------------------------------- |
| metadata name `../outside.bin`            | `FileProfileError`; the profile does not accept the metadata    |
| metadata contains `U+202E`                | `FileProfileError`; the first-party profile rejects the control |
| local name contains a surrogate code point | `FileProfileError`; it cannot become canonical UTF-8 metadata   |
| stream has no active file materializer    | `FileArchiveError` before the output directory is created       |
| members `Fruit.txt` and `fruit.TXT`       | `FileArchiveError`; portable comparison finds a duplicate       |
| source is a symlink or reparse point      | `FileProfileError`; no source handle is exposed                 |
| output root is a symlink or reparse point | `FileArchiveError`; no member is decoded or published           |
| target path already exists                | `FileArchiveError`; existing bytes remain untouched             |
| member count exceeds `max_members`        | `ResourceLimitError` before the output directory is created     |
| one member exceeds `max_member_bytes`     | `ResourceLimitError`; no final member is published              |
| total output exceeds `max_total_bytes`    | `ResourceLimitError`; temporary output is cleaned up            |

Each materializer returns a `FileMaterialization`, not a filesystem path or an
open handle. The archiver revalidates its basename before joining it with the
output directory. A stream profile cannot use metadata to request a directory,
path traversal, alternate data stream or arbitrary write target.

This path-based cross-platform adapter is safe for ordinary caller-owned
directories. It is not a privilege boundary for an output tree another actor
can replace concurrently. Such deployments need platform-specific
directory-handle and no-follow operations around the adapter.

These failures use the families defined in the [runtime error
reference](../errors.md). They are not evidence that the container framing or
payload CRC is corrupt.

## File extraction limits

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
and stage-execution limits still apply.

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

Origin and quarantine metadata belong to the caller or carrier context, not
to `obst.file@1`. The archiver never invents or copies member-controlled
extended attributes. On Windows, the first-party CLI warns when an input
container has `Zone.Identifier`, because the newly created members do not
inherit that Mark of the Web.

## Related documentation

- [File stream contract](../contracts/streams/file.md): normative
  `obst.file@1` metadata and logical bytes
- [Stream profiles](profiles.md): generic stream identity and optional metadata
  interpretation
- [Archivers and application adapters](archivers.md): the general adapter
  boundary
- [Packaging](../core/packaging.md): `LogicalStreamSource` and
  packager providers
- [Carriers](carriers.md): endpoint ownership and publication
- [Resource limits](../core/resources.md): core operation budgets
