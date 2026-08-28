# Transform Stages

Parent: [Extension system](README.md)

A transform is a [Stage Extension](stages.md) that rearranges or recodes bytes
so another Stage can represent them more effectively. It is a design role, not
a separate registry kind or provider protocol.

## Table of contents

- [Transform Stages](#transform-stages)
	- [Table of contents](#table-of-contents)
	- [Transform boundary](#transform-boundary)
	- [Chunk independence](#chunk-independence)
	- [Lossless scope](#lossless-scope)
	- [Concrete example](#concrete-example)

## Transform boundary

A transform participates in the same reversible Recipe contract as a codec:

```text
logical bytes -> transform -> codec -> encoded payload
logical bytes <- inverse   <- decode <- encoded payload
```

Encoding applies Stages in declaration order. Decoding applies inverse
operations in reverse order.

## Chunk independence

A transform must define alignment, reset behavior and malformed inputs. Hidden
state across calls makes independently framed chunks unsafe. Record-aware
transforms must state what happens when a chunk ends in the middle of a record.

## Lossless scope

Stages advertised as reversible cannot hide lossy conversion. Numeric scaling,
quantization and schema meaning belong to a versioned
[stream profile](profiles.md) whose logical-byte representation states that
meaning explicitly.

## Concrete example

The separately distributed
[`obst-defaults` transform guide](../../plugins/defaults/docs/transforms.md)
documents its Delta8 provider and normative contract.
