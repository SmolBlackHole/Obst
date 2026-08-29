# Extension registry

Parent: [Extension system](../extensions.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

The extension registry is the host-controlled composition point between OBST
core operations and installed extension objects. It validates offered
capabilities once, freezes them into an immutable lookup and never discovers
or downloads code from container bytes.

## Table of contents

- [Extension registry](#extension-registry)
	- [Table of contents](#table-of-contents)
	- [Compose extension objects](#compose-extension-objects)
	- [Freeze an immutable snapshot](#freeze-an-immutable-snapshot)
	- [Resolve capabilities](#resolve-capabilities)
	- [Inspect the capability inventory](#inspect-the-capability-inventory)
	- [Compose adapter-specific capabilities](#compose-adapter-specific-capabilities)
	- [Reject conflicts and invalid contracts](#reject-conflicts-and-invalid-contracts)
		- [Non-callable capabilities](#non-callable-capabilities)
		- [Capability conflicts](#capability-conflicts)
	- [Resolve typed wire codecs](#resolve-typed-wire-codecs)
	- [Look up optional interpreters](#look-up-optional-interpreters)
	- [Keep the trust boundary explicit](#keep-the-trust-boundary-explicit)
	- [Related documentation](#related-documentation)

## Compose extension objects

An extension object supplies its own versioned ID, kind, descriptor and every
capability it implements. Objects from every trusted source enter the same
builder:

```python
from collections.abc import Iterable

from obst.core import Extension, ExtensionRegistry, ExtensionRegistryBuilder


def build_registry(trusted_extensions: Iterable[Extension]) -> ExtensionRegistry:
    builder = ExtensionRegistryBuilder()
    for extension in trusted_extensions:
        builder.register(extension)
    return builder.build()
```

The builder is useful when an application assembles capabilities from several
explicit configuration sources. For a fixed collection, direct construction
produces the same immutable runtime type:

```python
from obst.core import ExtensionRegistry

registry = ExtensionRegistry(trusted_extensions)
```

The [Extension guide](../extensions.md) owns the provider protocols and
show how to implement an extension. The registry owns only validation,
composition and lookup.

Importing `obst.core` does not construct or activate providers. Directly
composed objects and explicitly loaded plugin contributions use the same
registry. Installed-plugin discovery and activation remain separate host
decisions.

## Freeze an immutable snapshot

`ExtensionRegistryBuilder` is mutable. Each `build()` call copies its current
capability records into a new immutable `ExtensionRegistry`. Registering
another object on the builder cannot change a registry that already exists.

Operations accept the immutable registry, never its builder. One packaging,
carrier, decoding or inspection operation therefore observes one stable set
of local capabilities even if the application prepares another registry at
the same time.

The registry exposes no mutable extension collection and no mutation method.
Core callers use its explicit capability lookups. Host adapters that define
additional protocols use the separately documented captured contributions
instead of reading extension identity again.

## Resolve capabilities

Stage lookups distinguish the 2 reversible directions:

```python
if registry.can_encode("org.example/codec@1"):
    encoder_provider = registry.require_encoder_provider("org.example/codec@1")

if registry.can_decode("org.example/codec@1"):
    decoder_provider = registry.require_decoder_provider("org.example/codec@1")
```

`can_encode()` and `can_decode()` are non-raising availability checks.
`require_encoder_provider()` and `require_decoder_provider()` return the
registered provider or raise `MissingStageError`. They do not bind parameters
or execute stage code.

[`RecipeEncoder` and `RecipeDecoder`](recipes.md#reuse-recipe-bindings) resolve
providers through those lookups, bind the recipe's exact opaque parameter
bytes and cache the resulting directional executors for their operation.

Carrier and packager providers use the same lookup boundary:

```python
reader_provider = registry.require_carrier_reader_provider("org.example/store@1")
packager_provider = registry.require_packager_provider("org.example/fixed@1")
```

Missing runtime capabilities raise `MissingExtensionCapabilityError`.
Provider-specific requests are bound only after lookup; neither lookup nor
inventory generation executes the selected operation.

`get_descriptor()` returns local descriptive metadata for any registered
extension ID. A missing descriptor returns `None`; the registry does not invent
one from a manifest declaration.

## Inspect the capability inventory

`capabilities()` returns a deterministic tuple of typed, provider-free
`ExtensionCapability` values sorted by extension ID:

```python
from obst.core import CarrierCapability, StageCapability

for capability in registry.capabilities():
    if isinstance(capability, StageCapability):
        print(capability.extension_id, capability.encoder_available)
    elif isinstance(capability, CarrierCapability):
        print(capability.extension_id, capability.reader_available)
```

The 4 record types are `StageCapability`, `StreamProfileCapability`,
`CarrierCapability` and `PackagerCapability`. Each includes the immutable
descriptor and only the availability fields meaningful for that kind. The
inventory never exposes provider objects or invokes extension code. Hosts can
therefore build diagnostics, capability negotiation inputs or CLI output
without reaching into registry internals.

Installed-package discovery remains a separate, explicit host operation. The
[plugin guide](../plugins.md) shows how inert entry-point metadata
becomes ordinary extension values before registry construction.

## Compose adapter-specific capabilities

`contributions()` returns trusted Extension objects paired with the exact ID,
kind and descriptor captured during registry construction:

```python
for contribution in registry.contributions():
    print(contribution.extension_id, contribution.kind.name.lower())
```

This is the supported attachment point for application adapters that define
their own optional protocols. The
[`obst-defaults` file adapter](../../../plugins/defaults/docs/files/profiles.md), for
example, recognizes file-source and file-materializer methods without teaching
the core what a file is.

The captured identity is authoritative for that registry. An adapter must not
read `extension.extension_id`, `extension.kind` or `extension.descriptor` again.
That rule prevents a stateful provider from appearing under one identity in
recipe execution and another identity in an adapter lookup.

Unlike `capabilities()`, contributions expose trusted executable extension
objects. They are not suitable for inert inventory output, negotiation data or
serialization. Reading the tuple does not execute a callback, but invoking a
provider method does.

An adapter checks one of its optional callable protocols through the captured
contribution instead of repeating static attribute inspection:

```python
provider = contribution.get_optional_callable_provider(
    "materialize_value",
    capability="example materializer",
)
```

The method returns the trusted Extension object when that member exists and is
callable, returns `None` when it is absent and raises `ExtensionContractError`
for a malformed advertised capability. It does not call the member. The
adapter still owns the protocol, type cast, per-ID conflict rules and domain
semantics.

## Reject conflicts and invalid contracts

Registration checks identity and capability shape before adding an object:

- `extension_id` must be an exact valid string;
- `descriptor` must be an exact `ExtensionDescriptor`;
- `kind` must be an exact `ExtensionKind` member; and
- every advertised registry capability member, including Stage binds, typed
  wire codecs, interpreters, carrier binds and `prepare_package`, must be
  callable.

Every descriptor may define one optional `specification_url`. The registry
exposes that same field for every Extension kind. Manifest construction may
copy it only for Stage and stream-profile IDs that the container actually
references; runtime-only carrier and packager IDs never enter container bytes.

An extension ID cannot identify 2 different extension kinds. Repeated
registrations under one ID must use the same descriptor, and 2 objects cannot
claim the same capability. Complementary objects may provide, for example,
carrier reading and publication or stage encoding and decoding under the same
ID when their descriptors agree.

Identity or callable-shape failures raise `ExtensionContractError`. Conflicting
IDs, descriptors or duplicate capabilities raise
`ExtensionRegistrationError`. Registration inspects callable shape but does
not bind parameters or invoke interpreter callbacks.

Callable presence does not prove a Python signature or result type. Stage
execution and inspection validate those details at their explicit callback
boundaries and report violations as `ExtensionContractError`. Carrier,
packager and adapter-specific protocols own their corresponding invocation and
failure boundaries outside the registry.

### Non-callable capabilities

Attribute presence is not enough. This object is rejected during registry
construction because `bind_encoder` advertises a capability that cannot be
called:

```python
from obst.core import (
    ExtensionContractError,
    ExtensionDescriptor,
    ExtensionKind,
    ExtensionRegistry,
)


class BrokenExtension:
    extension_id = "org.example/broken@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor()
    bind_encoder = 1


try:
    ExtensionRegistry((BrokenExtension(),))
except ExtensionContractError as error:
    assert error.extension_id == "org.example/broken@1"
    assert error.capability == "encoder provider"
```

The failure happens before recipe binding or container output. A method with an
incompatible signature is still callable, so registration alone cannot reject
it.

### Capability conflicts

Two objects cannot both own the same capability under one ID. Registering the
same complete codec twice is therefore an error, not last-registration-wins:

```python
from obst.core import (
    ExtensionDescriptor,
    ExtensionKind,
    ExtensionRegistrationError,
    ExtensionRegistry,
)


class EncoderExtension:
    extension_id = "org.example/codec@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor()

    def bind_encoder(self, parameters: bytes) -> object:
        raise NotImplementedError

try:
    ExtensionRegistry((EncoderExtension(), EncoderExtension()))
except ExtensionRegistrationError as error:
    assert error.extension_id == "org.example/codec@1"
```

Separate encoder-only and decoder-only objects may share an ID when their
descriptors agree. They are complementary capabilities rather than a conflict.
The [runtime error reference](../errors.md) owns the complete exception
taxonomy.

## Resolve typed wire codecs

Parameter and metadata serialization are optional generic capabilities. The
registry keeps their directions separate and does not invoke them during
lookup:

```python
from dataclasses import dataclass
from typing import cast

from obst.core import StageParameterEncoder


@dataclass(frozen=True)
class ExampleParameters:
    level: int


provider = registry.get_stage_parameter_encoder("org.example/codec@1")
if provider is None:
    raise RuntimeError("parameter authoring is unavailable")

parameter_encoder = cast(StageParameterEncoder[ExampleParameters], provider)
wire_parameters = parameter_encoder.encode_parameters(ExampleParameters(9))
```

The corresponding methods are:

- `get_stage_parameter_encoder()` and `get_stage_parameter_decoder()`;
- `get_stream_metadata_encoder()` and `get_stream_metadata_decoder()`.

The return type deliberately erases the contract-specific value type. A caller
must first select a known extension ID, then cast to the value type published
by that contract. This keeps the registry language-neutral while preserving a
typed Python authoring API.

## Look up optional interpreters

The registry stores optional inspection capabilities separately from stage
execution:

```python
parameter_interpreter = registry.get_stage_parameter_interpreter(stage_id)
metadata_interpreter = registry.get_stream_metadata_interpreter(stream_type)
```

These methods return the registered interpreter provider or `None`. Lookup does
not invoke extension code. [`inspect_container()`](../inspection.md) calls an
interpreter only when the host explicitly includes its ID in an
`InspectionInterpretationPolicy`.

Raw stage parameters and stream metadata remain authoritative even when a
local interpreter is available.

## Keep the trust boundary explicit

The application constructs extension objects and decides which ones enter a
registry. Registration accesses their identity and capability attributes, and
later core operations may call their providers. Extension objects are
therefore trusted in-process code, not passive data.

An OBST manifest only declares versioned IDs and optional specification URLs.
Those values never register extensions, import modules, fetch URLs or acquire
executables. A stage required by a chunk but absent from the selected registry
fails with `MissingStageError`.

Extension packages or host composition code produce ordinary extension objects
before registry construction. The container does not choose which code the
host trusts.

## Related documentation

- [Extension system](../extensions.md)
- [Stage providers](../extension-api/stages.md)
- [Recipe and chunk execution](recipes.md)
- [Container inspection](../inspection.md)
- [Runtime errors](../errors.md)
