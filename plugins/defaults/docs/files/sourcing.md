# Source and package files

Parent: [Portable files](README.md)

`FileArchiver.open_sources()` turns explicitly selected regular files into
bounded logical stream sources. This page owns source-handle validation and
shows how callers combine those sources with their chosen Recipe, Packager and
Carrier.

## Create logical stream sources

`open_sources()` is a context manager over a non-empty sequence of `Path`
values. On entry it rejects symbolic links, Windows reparse points,
non-regular files, invalid portable basenames and case-folded duplicate
basenames. Each accepted file is opened once, validated from that handle and
becomes one stream under the explicitly selected source profile and Recipe.

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

File contents remain lazy, but path resolution does not. The Packager reads
each source from the exact handle opened when the context was entered; it never
reopens the pathname. Leaving the context closes every handle, including after
packaging failure. One close failure never prevents the remaining handles from
being closed. An active packaging error stays primary and receives cleanup
failures as notes; after a successful body, the first close failure is raised
and later failures become notes.

This binds identity, not a frozen snapshot. Another process that can write
through the same file object may still change bytes while OBST reads it.

The default chunk size is 64 KiB; an explicit chunk size must be a positive
integer. Each source declares the selected size as its maximum logical chunk
size.

## Package the sources

Packaging keeps every owner visible. The archiver and Packager use the same
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

Selecting another Carrier changes where the completed container is published.
Selecting another Packager changes packaging policy. Replacing the supplied
Recipe changes how chunks are represented. Replacing the selected source
profile changes the stream contract; none of those choices changes the core
container API.

The [file-profile guide](profiles.md) owns capability composition. The
[fixed-packager guide](../packagers/fixed.md) owns its manifest and execution
policy, while [package execution](../carriers/package-execution.md) owns the
writer and publisher lifecycle.
