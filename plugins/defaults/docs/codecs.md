# Codecs supplied by obst-defaults

Parent: [obst-defaults documentation](README.md)

`obst-defaults` supplies two codec Stage Extensions. They use the ordinary
OBST Stage registry and binding contracts; there is no first-party execution
path.

## Table of contents

- [Codecs supplied by obst-defaults](#codecs-supplied-by-obst-defaults)
	- [Table of contents](#table-of-contents)
	- [Available codecs](#available-codecs)
	- [Compose the providers](#compose-the-providers)
	- [Author Stage parameters](#author-stage-parameters)
	- [Related documentation](#related-documentation)

## Available codecs

| Extension     | Purpose                                          | Contract                                               | Python provider           |
| ------------- | ------------------------------------------------ | ------------------------------------------------------ | ------------------------- |
| `obst.zlib@1` | zlib-wrapped DEFLATE without a preset dictionary | [zlib](contracts/stages/zlib.md)                       | `ZlibExtension`           |
| `obst.zlib@2` | zlib-wrapped DEFLATE with a preset dictionary    | [zlib dictionary](contracts/stages/zlib-dictionary.md) | `ZlibDictionaryExtension` |

## Compose the providers

```python
from obst.core import ExtensionRegistry
from obst_defaults.codecs import (
    ZlibDictionaryExtension,
    ZlibExtension,
)

registry = ExtensionRegistry(
    (ZlibExtension(), ZlibDictionaryExtension())
)
```

The registry treats them exactly like providers from any other activated
plugin. Conflicting providers for the same Extension ID and capability are
rejected.

## Author Stage parameters

Opaque parameter bytes are authored by the Extension that owns their contract:

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

`encode_parameters()` creates the exact bytes later passed to parameter
decoding and Stage binding. The individual contracts remain authoritative for
their language-neutral representation.

## Related documentation

- [Generic Stage API](../../../docs/extensions/stages.md)
- [Recipe execution](../../../docs/core/recipes.md)
- [Plugin contract index](contracts/README.md)
