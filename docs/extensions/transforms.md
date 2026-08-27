# Transforms

Parent: [Extension system](README.md)

A transform is a [Stage Extension](stages.md) that rearranges or recodes bytes
so another stage can represent them more effectively. It is a role, not a
separate core protocol or registry type. Like every stage, it must remain
exactly reversible and chunk-local.

## Table of contents

- [Transforms](#transforms)
	- [Table of contents](#table-of-contents)
	- [First-party transform](#first-party-transform)
	- [Contract boundaries](#contract-boundaries)

A recipe may combine transforms with codecs:

```text
logical bytes -> transform -> codec -> encoded payload
logical bytes <- inverse   <- decode <- encoded payload
```

## First-party transform

| Extension       | Purpose                | Normative contract                      | Python provider   |
| --------------- | ---------------------- | --------------------------------------- | ----------------- |
| `obst.delta8@1` | Modulo-256 byte deltas | [Delta8](../contracts/stages/delta8.md) | `Delta8Extension` |

```python
from obst.core import ExtensionRegistry
from obst_defaults.transforms import Delta8Extension

registry = ExtensionRegistry((Delta8Extension(),))
```

`Delta8Extension` is a self-describing object with the same binding and
execution path available to third-party stages. It receives empty parameters,
binds once per recipe and direction, and applies no state across chunks.

## Contract boundaries

A transform must define chunk alignment and state explicitly. Hidden state
across calls would make independently processed chunks unsafe. Record-aware
transforms must define what happens when a chunk ends in the middle of a
record.

The exact Delta8 formulas, reset rule and invalid inputs belong to its
[normative contract](../contracts/stages/delta8.md), not this Python extension
guide.

Lossy conversion does not belong in a stage advertised as reversible. Numeric
scaling, quantization and schema meaning belong in a versioned
[stream profile](profiles.md) whose logical-byte encoding states the loss
explicitly.
