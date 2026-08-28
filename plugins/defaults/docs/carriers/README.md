# obst-defaults Carriers

Parent: [obst-defaults documentation](../README.md)

These runtime-only Extensions bind complete OBST byte streams to concrete
endpoints. Their IDs never enter container bytes and activating them never
changes format validity.

## Available Carriers

- [`obst.filesystem@1`](filesystem.md): read a path or transactionally publish
  a new path.
- [`obst.memory@1`](memory.md): read or publish a complete in-memory stream.
- [`obst.stdin@1`](standard-input.md): read a host-owned standard-input
  endpoint.

## Package execution

[Package execution](package-execution.md) documents the plugin's
`write_package()` and `publish_package()` helpers. It owns their close, commit,
abort and cleanup semantics.

## Shared contract

The OBST runtime owns the generic [Carrier provider and lifecycle
contracts](../../../../docs/extensions/carriers.md).
