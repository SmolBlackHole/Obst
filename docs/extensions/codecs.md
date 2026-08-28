# Codec Stages

Parent: [Extension system](README.md)

A codec is a [Stage Extension](stages.md) whose main purpose is compression or
another stored representation. It is a design role, not a separate registry
kind or provider protocol.

## Table of contents

- [Codec Stages](#codec-stages)
	- [Table of contents](#table-of-contents)
	- [Codec boundary](#codec-boundary)
	- [Parameters and identity](#parameters-and-identity)
	- [Implementation guidance](#implementation-guidance)
	- [Concrete examples](#concrete-examples)

## Codec boundary

A codec receives one bounded chunk at a time and returns bytes. It must define
an exact inverse, reject malformed parameters or payloads through the public
provider boundary, and obey the operation's output limits.

The core owns Stage binding, execution order, error translation and resource
accounting. A codec owns its algorithm and its exact parameter-byte contract.

## Parameters and identity

Changing the meaning of parameter bytes, accepted payloads or recovered output
requires a new versioned Extension ID. An encoder may evolve internally while
retaining an ID only when every emitted representation remains valid under the
same published decoding contract.

Typed parameter-authoring helpers belong to the Extension that owns those
bytes. They must not become a second, silently divergent wire definition.

## Implementation guidance

Codec providers should be stateless or safely reusable after binding. Hidden
state across chunks breaks independent framing, bounded scheduling and
parallel execution. A provider must never fetch code or capabilities based on
container input.

See the [Stage guide](stages.md) for complete provider protocols and
[Recipe execution](../core/recipes.md) for forward and inverse ordering.

## Concrete examples

The separately distributed
[`obst-defaults` codec guide](../../plugins/defaults/docs/codecs.md) documents
its RAW and zlib providers. Those algorithms and parameter contracts are owned
and tested by that plugin, not by this generic runtime page.
