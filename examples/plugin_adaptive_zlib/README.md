# Adaptive-zlib extension plugin

Parent: [Examples](../README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

This directory is a complete, installable third-party OBST plugin. Its Stage
tries several reversible byte layouts and preset dictionaries for every chunk,
then stores only the smallest zlib representation it found. The decoder reads
the recorded choice and never repeats the search.

The package uses only public OBST APIs and receives no first-party shortcut.
It is intentionally more involved than a minimal identity or byte-swap example
because it demonstrates what "the encoder may be smart" means at one extension
boundary.

## Table of contents

- [Adaptive-zlib extension plugin](#adaptive-zlib-extension-plugin)
	- [Table of contents](#table-of-contents)
	- [Install it](#install-it)
	- [Discover and activate it](#discover-and-activate-it)
	- [Stage contract](#stage-contract)
		- [Parameters](#parameters)
		- [Chunk payload](#chunk-payload)
		- [Encoder freedom](#encoder-freedom)
	- [Use it directly](#use-it-directly)
	- [Run the sample comparison](#run-the-sample-comparison)
	- [Test the contract](#test-the-contract)
	- [Trust boundary](#trust-boundary)
	- [Package structure](#package-structure)

## Install it

From the OBST checkout, install the runtime, the independently packaged
first-party defaults and the example plugin into the same environment:

```console
python -m pip install -e . -e ./plugins/defaults -e ./examples/plugin_adaptive_zlib
```

The distribution publishes ordinary plugin entry points:

```toml
[project.entry-points."obst.extensions"]
adaptive-zlib = "obst_example_adaptive_zlib:obst_extensions"

[project.entry-points."obst.conformance"]
adaptive-zlib = "obst_example_adaptive_zlib.conformance:obst_conformance"

[project.entry-points."obst.commands"]
adaptive-zlib = "obst_example_adaptive_zlib:obst_commands"
```

The extension factory returns one complete `AdaptiveZlibExtension` object. Its
identity, descriptor, parameter codec, interpreter and directional providers
all live on that object.

## Discover and activate it

Discovery reads package metadata without importing the plugin:

```console
obst plugins list
```

Persistent activation remains an explicit host decision:

```console
obst plugins enable adaptive-zlib
obst extensions
```

Activation also makes the plugin's `adaptive-pack` command available. Its
Recipe contains only the adaptive Stage; unchanged bytes need no separate
identity provider:

```console
obst adaptive-pack README.md -o readme-adaptive.obst
obst adaptive-pack README.md -o readme-adaptive.obst --json
```

The JSON variant emits schema `1` with the destination, exact logical and
container sizes and the number of written chunks.

The capability inventory then includes:

```text
org.example/adaptive-zlib@1 (Adaptive zlib)
    stage | encode yes | decode yes
    parameter encoding yes | decoding yes | interpretation yes
```

Applications can select the same contribution through `PluginManager`:

```python
from obst.plugins import PluginManager

manager = PluginManager.discover()
runtime = manager.runtime(additional=("adaptive-zlib",))
```

`runtime.registry` is the same ordinary immutable `ExtensionRegistry` used by
direct composition.

## Stage contract

`org.example/adaptive-zlib@1` is a chunk-local codec. For every logical chunk,
an encoder may try the declared byte-lane layouts with no dictionary and with
each declared preset dictionary. It emits one selected layout, one dictionary
index and one zlib-wrapped DEFLATE stream.

Encoding one fixed-width byte sequence with width 2 illustrates the layout:

```text
logical:  A0 A1  B0 B1  C0 C1  FF
shuffled: A0 B0 C0  A1 B1 C1  FF
```

Only complete elements are shuffled. Remaining tail bytes stay in their
original order. Width 1 means no shuffle.

### Parameters

The typed Python value is:

```python
AdaptiveZlibParameters(
    compression_level=9,
    shuffle_widths=(1, 2, 4, 8),
    dictionaries=(dictionary_a, dictionary_b),
)
```

Its canonical parameter bytes are:

| Offset | Type             | Meaning                                     |
| -----: | ---------------- | ------------------------------------------- |
|      0 | `u8`             | zlib compression level, `0..9`              |
|      1 | `u8` bit mask    | declared shuffle widths 2, 4, 8 and 16      |
|      2 | `u8`             | dictionary count, `0..8`                    |
|      3 | repeated entries | `u16` big-endian size followed by the bytes |

Width 1 and dictionary index 0 are always implicit candidates. Each declared
dictionary contains 1 to 32,768 bytes. Duplicate dictionaries, trailing
parameter bytes and unknown mask bits are invalid.

### Chunk payload

The encoded Stage payload is:

| Offset | Type    | Meaning                                                |
| -----: | ------- | ------------------------------------------------------ |
|      0 | `u8`    | layout: raw, shuffle2, shuffle4, shuffle8 or shuffle16 |
|      1 | `u8`    | dictionary index, 0 means no dictionary                |
|      2 | `bytes` | one complete zlib-wrapped DEFLATE stream               |

The selected layout and dictionary must be declared by the Stage parameters.
The dictionary identifier in a preset-dictionary zlib header must match the
selected dictionary's Adler-32 value. Trailing zlib data, unknown modes and
invalid framing are rejected.

### Encoder freedom

The reference encoder compresses every declared combination and selects the
shortest exact Stage payload. Ties prefer the lower layout mode and then the
lower dictionary index.

That search strategy is not required for interoperability. Another encoder may
use sampling, hardware acceleration, a different cost model or considerably
more electricity. Every declared combination is decodable, so the static
known-answer records deliberately mark their encoded bytes as non-canonical.

The decoder only performs:

```text
read layout and dictionary index
    -> validate the declared choice
    -> decompress once
    -> invert one shuffle
```

The plugin imports Python's standard-library `zlib` implementation. It does not
import or delegate to OBST's `ZlibExtension`; `org.example/adaptive-zlib@1` owns
its complete language-neutral contract.

## Use it directly

```python
from obst.core import (
    DEFAULT_RESOURCE_POLICY,
    ExtensionRegistry,
    Recipe,
    ResourceAccounting,
    StageSpec,
    decode_recipe,
    encode_recipe,
)
from obst_example_adaptive_zlib import (
    AdaptiveZlibExtension,
    AdaptiveZlibParameters,
)

extension = AdaptiveZlibExtension()
parameters = extension.encode_parameters(AdaptiveZlibParameters(compression_level=9))
registry = ExtensionRegistry((extension,))
recipe = Recipe(0, (StageSpec(extension.extension_id, parameters),))
logical = b"".join(index.to_bytes(8, "little") for index in range(4096))
accounting = ResourceAccounting(DEFAULT_RESOURCE_POLICY)

encoded = encode_recipe(logical, recipe, registry, accounting=accounting)
recovered = decode_recipe(
    encoded,
    recipe,
    registry,
    expected_size=len(logical),
    accounting=accounting,
)

assert recovered == logical
```

## Run the sample comparison

[`compare_samples.py`](compare_samples.py) uses a synthetic fixed-width dataset
and then treats `samples/all-fruit.obst` as ordinary input bytes:

```console
python examples/plugin_adaptive_zlib/compare_samples.py
```

The script compares Stage payload sizes with ordinary fixed zlib, counts the
chosen modes, includes adaptive parameter bytes once and verifies both round
trips dynamically.

The structured records benefit substantially from shuffle8. The existing OBST
container is already largely compressed; a dictionary trained from
`samples/apple.obst` finds some matches, but its declared bytes cost more than
they save. That is a valid and useful result. An adaptive encoder does not make
incompressible bytes feel guilty until they become smaller.

## Test the contract

The plugin ships a static suite with 2 known answers plus parameter,
malformed-input and output-limit cases:

```console
obst plugins test adaptive-zlib
```

The suite lives in one packaged `index.json` with inline hexadecimal bytes. It
verifies known decoding and local round trips without demanding one canonical
encoder choice. Regenerate the checked-in catalog from the repository root
with:

```console
python examples/plugin_adaptive_zlib/scripts/build_conformance.py
```

## Trust boundary

Loading or testing the plugin executes installed third-party Python code. The
conformance command is not a sandbox. Container bytes can reference
`org.example/adaptive-zlib@1`, but they cannot install, enable or load this
plugin.

Malformed parameter bytes and payloads are refused with the public
`ProviderRejectedError` protocol signal. Local construction of invalid typed
parameters raises `TypeError` or `ValueError`. The plugin owns no filesystem,
archive or carrier semantics.

## Package structure

```text
plugin_adaptive_zlib/
    pyproject.toml
    README.md
    compare_samples.py
    scripts/
        build_conformance.py
        quality.py
    src/obst_example_adaptive_zlib/
        __init__.py
        commands.py
        conformance.py
        conformance_vectors/
            index.json
        extension.py
    tests/
```
