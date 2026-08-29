# Stage extensions

Parent: [Extension system](README.md)

A stage is a versioned, reversible byte-to-byte contract applied to one
[chunk](../anatomy.md#chunks-make-the-stream-bounded). Encoding follows
[recipe](../core/recipes.md) order; decoding applies the inverse stages in
reverse order.

## Table of contents

- [Stage extensions](#stage-extensions)
	- [Table of contents](#table-of-contents)
	- [Stable identity](#stable-identity)
	- [Provider protocols](#provider-protocols)
	- [Typed parameter codecs](#typed-parameter-codecs)
	- [Binding and execution](#binding-and-execution)
	- [Register the extension](#register-the-extension)
	- [Parameters, limits and errors](#parameters-limits-and-errors)
		- [Invalid parameters](#invalid-parameters)
		- [Invalid provider output](#invalid-provider-output)
	- [Inspection parameters](#inspection-parameters)
	- [Reentrancy and determinism](#reentrancy-and-determinism)
	- [Contract and test checklist](#contract-and-test-checklist)

## Stable identity

The full ID names a language-neutral contract:

```text
org.example/reverse@1
```

It identifies exact parameter bytes, forward and inverse behavior, malformed
input handling and resource rules. It does not identify a Python class or
distribution. Two providers under one ID claim to implement the same contract.

The `obst` namespace is reserved for contracts published by this project.
Third parties use a namespace they control. Incompatible behavior requires a
new versioned ID.

`ExtensionDescriptor` adds local presentation metadata. The extension object,
not the descriptor, owns the canonical ID. Its specification URL is advisory
provenance: OBST may serialize and display it, but never fetches it or treats it
as executable discovery metadata.

## Provider protocols

Providers use structural protocols. No OBST base class, wrapper or decorator
is required. One object exposes its identity, descriptor and the capabilities
it implements:

> [!WARNING]
> **Executable documentation:** The following Python block runs during tests
> with the current process privileges. It is not sandboxed.

```python
from typing import Self

from obst.core import (
    DEFAULT_RESOURCE_POLICY,
    ExtensionDescriptor,
    ExtensionKind,
    ExtensionRegistry,
    InspectionField,
    InspectionInterpretation,
    Recipe,
    ResourceAccounting,
    StageSpec,
    decode_recipe,
    encode_recipe,
    require_no_parameters,
    require_stage_output_size,
)


class ReverseExtension:
    extension_id = "org.example/reverse@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        display_name="Reverse",
        summary="Reverse the bytes in one chunk.",
        specification_url="https://example.org/obst/reverse-v1",
    )

    def bind_encoder(self, parameters: bytes, /) -> Self:
        require_no_parameters(self.extension_id, parameters)
        return self

    def bind_decoder(self, parameters: bytes, /) -> Self:
        require_no_parameters(self.extension_id, parameters)
        return self

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        require_stage_output_size(
            self.extension_id,
            len(data),
            max_output_size=max_output_size,
            operation="encode",
        )
        return data[::-1]

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        # Reversal is its own inverse.
        return self.encode(data, max_output_size=max_output_size)

    def interpret_parameters(
        self,
        parameters: bytes,
        /,
    ) -> InspectionInterpretation:
        if parameters:
            return InspectionInterpretation(error="expected empty parameters")
        return InspectionInterpretation(
            fields=(InspectionField("mode", "reverse"),)
        )


reverse = ReverseExtension()
registry = ExtensionRegistry((reverse,))
recipe = Recipe(0, (StageSpec(reverse.extension_id),))
logical = b"fruit travels both ways"
accounting = ResourceAccounting(DEFAULT_RESOURCE_POLICY)

encoded = encode_recipe(logical, recipe, registry, accounting=accounting)
assert encoded == logical[::-1]
assert (
    decode_recipe(
        encoded,
        recipe,
        registry,
        expected_size=len(logical),
        accounting=accounting,
    )
    == logical
)
```

Delegating `decode()` to `encode()` is correct here because reversal is
self-inverse. Most codecs require different bound operations for the 2
directions; sharing an implementation is correct only when the versioned Stage
contract defines the same operation both ways.

An extension package exports `ReverseExtension` or a configured instance.
Importing it has no global side effect.

## Typed parameter codecs

`StageParameterEncoder[T]` and `StageParameterDecoder[T]` are independent,
optional capabilities on the same extension object. The versioned stage
contract owns `T`; the core only standardizes the mapping between that typed
local value and authoritative parameter bytes.

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExampleParameters:
    mode: int


class ExampleExtension:
    def encode_parameters(self, value: ExampleParameters, /) -> bytes:
        return bytes((value.mode,))

    def decode_parameters(self, parameters: bytes, /) -> ExampleParameters:
        if len(parameters) != 1:
            raise ValueError("expected exactly 1 mode byte")
        return ExampleParameters(parameters[0])
```

The registry resolves both directions separately. A provider may therefore
support authoring, reading, both or neither. The generic value type is erased
at lookup; code selecting a known stage ID casts to that contract's documented
type before invoking the provider.

These methods are not `bind_parameter_encoder()` or
`bind_parameter_decoder()`. They perform one serialization operation. Binding
is reserved for turning exact parameter bytes into a reusable chunk executor.

## Binding and execution

`StageSpec.parameters` contains exact contract-owned bytes. The registry
returns a provider without executing it. A `RecipeEncoder` or `RecipeDecoder`
then binds those bytes to a directional executor:

```text
exact StageSpec.parameters
        |
        v
bind_encoder(parameters) or bind_decoder(parameters)
        |
        v
operation-local bound executor
        |
        v
encode(chunk, max_output_size=...) or decode(...)
```

Binding validates and parses the parameters once for each stage position in a
recipe and direction during one operation. The resulting executor may process
multiple chunks without receiving or reparsing those parameters. Binding must
not normalize or replace the authoritative wire bytes.

Encoder preflight resolves every provider required by all declared recipes
before invoking the first bind callback or publishing container bytes. Decoder
binding is lazy: only a recipe referenced by a decoded chunk is resolved and
bound. Within either recipe, all required providers are resolved before its
first bind callback runs.

The [recipe execution guide](../core/recipes.md) owns the operation lifecycle.

## Register the extension

The complete example above constructs the extension and places it in an
explicit, immutable registry before executing either direction.

Registry construction, split directional providers, conflicts and immutable
snapshots belong to the [registry guide](../core/registry.md). A stage package
only exports its self-describing class or a configured instance. It does not
mutate a process-global registry during import.

## Parameters, limits and errors

`require_no_parameters()` implements the common empty-parameter contract.
Both bound directions receive `max_output_size: int | None`. A finite value is
the host's output ceiling. `None` means the host explicitly disabled that one
local limit. Providers should enforce a finite ceiling before or while
allocating. The core then requires exact built-in `bytes` and checks the size
again.

`require_stage_output_size()` applies the shared refusal semantics before a
known-size allocation. Incremental encoders can use `extend_stage_output()` to
check the resulting `bytearray` size before appending each exact `bytes` part.
The helper cannot undo work already performed while producing that part, so a
provider must still use bounded operations offered by its underlying codec.

```python
from collections.abc import Iterable

from obst.core import extend_stage_output


def collect_stage_output(
    stage_id: str,
    parts: Iterable[bytes],
    *,
    max_output_size: int | None,
) -> bytes:
    output = bytearray()
    for part in parts:
        extend_stage_output(
            output,
            part,
            stage_id=stage_id,
            max_output_size=max_output_size,
            operation="encode",
        )
    return bytes(output)
```

The provider boundary distinguishes expected data refusal from a broken
provider contract:

- an exact `ProviderRejectedError` becomes a `PipelineError` carrying the stage
  ID, direction and `bind` or `execute` phase;
- output refusal raised through the public size helpers retains its structured
  `ResourceLimitError`;
- a `ProviderRejectedError` subclass or malformed rejection becomes
  `ExtensionContractError` without consulting provider-defined attributes;
- a missing direction raises `MissingStageError` before provider code runs;
- registration conflicts raise `ExtensionRegistrationError`; and
- a wrong signature, invalid bound executor, non-`bytes` result or unexpected
  `Exception` becomes `ExtensionContractError` with the original exception as
  `__cause__`.

That last rule also applies when provider code raises an arbitrary `ObstError`.
Extensions must use `ProviderRejectedError` for their expected stage-local
refusals. `BaseException` subclasses outside `Exception` are not converted.

Providers are trusted local code with the complete authority of the host
process. These checks produce stable diagnostics for broken contracts; they do
not sandbox extensions. The [runtime error reference](../errors.md) owns the
complete hierarchy, while [resource limits](../core/resources.md) owns shared
operation accounting.

### Invalid parameters

The reverse example accepts no parameter bytes. It rejects a non-empty value
while binding, before any chunk is processed:

```python
from obst.core import ProviderRejectedError

try:
    reverse.bind_encoder(b"\x01")
except ProviderRejectedError as error:
    assert "does not accept parameters" in error.reason
```

Through `encode_recipe()`, the core wraps that expected stage-local refusal in
`PipelineError` with the stage ID, direction and `bind` phase. An extension
should not silently ignore unknown bytes, because those bytes are part of its
versioned language-neutral contract.

### Invalid provider output

Type annotations do not validate runtime values. This executor violates the
provider contract even though `bytearray` contains bytes:

```python
class BrokenEncoder:
    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        return bytearray(data)  # type: ignore[return-value]
```

The core rejects the result with `ExtensionContractError` before calling
`len()` or charging it to a resource budget. It does not normalize the value
with `bytes(result)`: conversion would invoke extension-controlled behavior and
hide a broken provider contract.

## Inspection parameters

`interpret_parameters()` is an optional method on the same self-describing
extension object. It returns presentation data without changing the
authoritative parameter bytes.

Fields use exact built-in `str`, `int`, `bool` or `None` values and unique
string names. Labels and errors are exact non-empty strings when present. The
same rules run when values are constructed and again at the interpreter
boundary. An interpretation error is a diagnostic, not a replacement for the
bytes.

The registry only returns the interpreter capability. It never invokes it.
Inspection calls the method only when the host includes the extension ID in an
explicit `InspectionInterpretationPolicy`. Structural inspection remains
callback-free. Raised exceptions and invalid returns stop inspection with
`ExtensionContractError` while preserving the original cause. The
[inspection guide](../core/inspection.md#optional-interpretation) defines that
policy boundary.

## Reentrancy and determinism

Provider objects and bound executors must be stateless or reentrant. Per-chunk
codec state belongs inside one `encode()` or `decode()` call. An implementation
may allocate, pool or lock its own native resources as long as concurrent calls
through the same bound executor remain safe.

Deterministic encoded output is a provider-to-host guarantee, not a property
inferred from a Stage ID. Some normative contracts allow multiple encoded byte
strings for the same logical input. A host that requires reproducible complete
containers must select providers that promise deterministic output for the
same input, parameters and configuration. The core verifies exact types,
limits and recovery; it does not compare separate provider runs.

## Contract and test checklist

Publish the language-neutral contract before reusing an ID. Cover exact
round-trips, empty and boundary inputs, malformed parameters and payloads,
output limits, encoder-only and decoder-only installations, registration
conflicts, repeated and concurrent calls against one bound executor, and
golden vectors shared across implementations.

The pytest-independent
[`obst.conformance`](../conformance.md#plugin-extension-suites) runner checks
static known answers, parameters, rejected inputs and output limits without
discovering plugin-owned test modules. A provider repository can load its
`ConformanceSuite` and pass its explicit Extension objects directly to
`run_conformance_suite()`; the plugin manager invokes the same public runner.
