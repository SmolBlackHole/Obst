# File profiles

Parent: [Portable files](README.md)

The Defaults file adapter discovers directional file capabilities by exact
stream-profile ID. This page owns those Python protocols and their composition;
the [`obst.file@1` contract](../contracts/streams/file.md) separately owns the
wire-visible basename and logical-byte rules.

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
  ID and runs the plugin's documented [extraction workflow](extraction.md).

The caller owns the registry, Recipe, Packager, Carrier, resource policy and
publication lifecycle. `FileArchiver` receives one immutable registry and
never discovers plugins or chooses hidden codec policy. The general
[application-adapter guide](../../../../docs/extensions/archivers.md#compose-an-adapter)
owns that flow.

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
captured contributions. The Recipe is not bound to the archiver. Packaging
supplies a source profile ID and Recipe per request; extraction uses the stream
type and Recipe IDs declared by the container.

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
