# Codecs

Parent: [Extension system](README.md)

A codec is a [Stage Extension](stages.md) whose main purpose is compression or
another encoded representation. It is a role, not a separate core protocol or
registry type. Codecs receive one bounded chunk at a time and own their exact
parameter bytes.

## Table of contents

- [Codecs](#codecs)
	- [Table of contents](#table-of-contents)
	- [First-party codecs](#first-party-codecs)
	- [Author parameters through the extension](#author-parameters-through-the-extension)

## First-party codecs

| Extension     | Purpose                                | Normative contract                                        | Python provider           |
| ------------- | -------------------------------------- | --------------------------------------------------------- | ------------------------- |
| `obst.raw@1`  | Identity fallback                      | [RAW](../contracts/stages/raw.md)                         | `RawExtension`            |
| `obst.zlib@1` | Dictionary-free zlib-wrapped DEFLATE   | [zlib](../contracts/stages/zlib.md)                       | `ZlibExtension`           |
| `obst.zlib@2` | zlib-wrapped DEFLATE with a dictionary | [zlib dictionary](../contracts/stages/zlib-dictionary.md) | `ZlibDictionaryExtension` |

Each provider is an ordinary self-describing extension object:

```python
from obst.core import ExtensionRegistry
from obst_defaults.codecs import (
    RawExtension,
    ZlibDictionaryParameters,
    ZlibDictionaryExtension,
    ZlibExtension,
    ZlibParameters,
)

registry = ExtensionRegistry(
    (RawExtension(), ZlibExtension(), ZlibDictionaryExtension())
)
```

They have no private execution path. A third-party codec is registered,
inspected, bound and executed through the same contracts. The
[stage identity rules](stages.md#stable-identity) define when another provider
may claim one of those IDs.

## Author parameters through the extension

Opaque parameter bytes are authored by the concrete extension that consumes
them. This keeps the public convenience API beside the wire contract instead
of creating parallel free functions:

```python
from obst.core import StageSpec
from obst_defaults.codecs import (
    ZlibDictionaryExtension,
    ZlibDictionaryParameters,
    ZlibExtension,
    ZlibParameters,
)

zlib_v1 = ZlibExtension()
zlib_v2 = ZlibDictionaryExtension()

dictionary_free = StageSpec(
    zlib_v1.extension_id,
    zlib_v1.encode_parameters(ZlibParameters(9)),
)
with_dictionary = StageSpec(
    zlib_v2.extension_id,
    zlib_v2.encode_parameters(
        ZlibDictionaryParameters(9, b"common-prefix:")
    ),
)
```

`encode_parameters()` accepts one contract-specific typed value and creates
the exact bytes subsequently passed back to that extension's
`decode_parameters()`, `bind_encoder()` or `bind_decoder()`. Parameter decoding
is available independently for tooling; binding parses the same bytes once per
recipe and direction during an operation. The
[dictionary-free](../contracts/stages/zlib.md) and
[preset-dictionary](../contracts/stages/zlib-dictionary.md) contracts remain
the language-neutral authority for their representation.
