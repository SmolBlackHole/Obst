# Portable files

Parent: [obst-defaults documentation](../README.md)

The first-party file feature maps explicit regular files to portable
`obst.file@1` logical streams and restores compatible file streams to a
filesystem. Its contracts, directional capabilities and adapter operations
remain separate so callers can replace each selected provider.

## File contract

The [`obst.file@1` stream contract](../contracts/streams/file.md) owns the
wire-visible basename and logical-byte rules. It assigns neither a Recipe nor
a chunk size.

## Python capabilities

- [File profiles](profiles.md) explains `FileExtension`, `FileSourceProfile`,
  `FileMaterializer` and adapter composition by exact stream-profile ID.
- [Source and package files](sourcing.md) documents handle-bound file sources
  and their composition with a selected Recipe, Packager and Carrier.
- [Extract files](extraction.md) documents materializer selection, safe
  filesystem publication, extraction limits and rollback behavior.

## Shared runtime contracts

The OBST runtime owns generic [stream profiles](../../../../docs/extensions/profiles.md),
[application adapters](../../../../docs/extensions/archivers.md),
[packaging](../../../../docs/core/packaging.md) and
[Carriers](../../../../docs/extensions/carriers.md). This plugin documents only
the concrete file capabilities and policies it supplies.
