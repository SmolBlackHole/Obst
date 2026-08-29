# obst-defaults Stage contracts

Parent: [obst-defaults contracts](../README.md)

Each Stage contract is independently versioned. Recipes may combine these
Stages with each other or with compatible Stages from other plugins.

## Contracts

- [`obst.delta8@1`](delta8.md): modulo-256 byte deltas.
- [`obst.zlib@1`](zlib.md): zlib-wrapped DEFLATE without a preset dictionary.
- [`obst.zlib@2`](zlib-dictionary.md): zlib-wrapped DEFLATE with a declared
  preset dictionary.

## Provider guide

See [Codecs](../../codecs.md), [Transforms](../../transforms.md) and the generic
[Stage API](../../../../../docs/extensions/stages.md).
