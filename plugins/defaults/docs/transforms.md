# Transforms supplied by obst-defaults

Parent: [obst-defaults documentation](README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

`obst-defaults` supplies the `obst.delta8@1` byte transform. It is an ordinary
Stage Extension intended to expose patterns to a later codec.

## Delta8 provider

```python
from obst.core import ExtensionRegistry
from obst_defaults.transforms import Delta8Extension

registry = ExtensionRegistry((Delta8Extension(),))
```

`Delta8Extension` accepts empty parameters, binds once per Recipe and
direction, and carries no state across chunks. Its exact arithmetic and reset
rule are defined by the [`obst.delta8@1` contract](contracts/stages/delta8.md).

## Recipe composition

The transform can precede a codec in a multi-Stage Recipe:

```text
logical bytes -> Delta8 -> codec -> encoded payload
logical bytes <- Delta8 <- codec <- encoded payload
```

Encoding applies Stages in declaration order. Decoding applies their inverse
operations in reverse order.

## Contract boundary

The generic [Stage API](../../../docs/toolchain/extension-api/stages.md) owns binding,
provider failures and chunk-local execution. Lossy conversion is not a
reversible Stage; application-level numeric meaning belongs to a versioned
[stream profile](../../../docs/toolchain/extension-api/profiles.md).
