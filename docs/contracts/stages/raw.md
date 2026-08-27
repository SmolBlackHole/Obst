# `obst.raw@1` stage contract

Parent: [Normative contracts](../../README.md#normative-contracts)

Status: experimental first-party stage contract.

Contract type: reversible, chunk-local pipeline stage.

`obst.raw@1` is the identity representation. It is useful as an explicit
fallback when no other recipe improves the payload.

## Table of contents

- [`obst.raw@1` stage contract](#obstraw1-stage-contract)
	- [Table of contents](#table-of-contents)
	- [Logical input and output](#logical-input-and-output)
	- [Parameters](#parameters)
	- [Forward operation](#forward-operation)
	- [Inverse operation](#inverse-operation)
	- [Chunk boundaries and state](#chunk-boundaries-and-state)
	- [Invalid inputs](#invalid-inputs)
	- [Resource behavior](#resource-behavior)
	- [Inspection](#inspection)
	- [Conformance](#conformance)
	- [Python reference implementation](#python-reference-implementation)

## Logical input and output

The logical input and encoded output are arbitrary finite byte strings. The
stage preserves both the length and every byte.

## Parameters

The parameter byte string is empty. Any non-empty value is invalid.

## Forward operation

For every input byte string `input`:

```text
encode(input) = input
```

The output has exactly the same length and bytes as the input.

## Inverse operation

For every encoded byte string `encoded`:

```text
decode(encoded) = encoded
```

The output has exactly the same length and bytes as the encoded input.

## Chunk boundaries and state

Each chunk is processed independently. The stage has no state before, after or
across chunks. Empty chunks are valid.

## Invalid inputs

Only non-empty parameters are invalid. Every encoded byte string is otherwise
a valid RAW payload.

## Resource behavior

Both directions require output space equal to the input length. An
implementation must reject an operation whose output would exceed the caller's
configured output limit.

## Inspection

There are no parameters to interpret.

## Conformance

At minimum, a conforming implementation verifies `empty -> empty` and
`00 ff -> 00 ff` in both directions. The complete RAW container vector lives in
[`minimal-raw.hex`](../../../conformance/containers/0.1-apple/golden/minimal-raw.hex). Stage-level
tests cover parameter rejection, output budgets and byte identity.

## Python reference implementation

[`plugins/defaults/src/obst_defaults/codecs/raw.py`](../../../plugins/defaults/src/obst_defaults/codecs/raw.py)
provides `RawExtension`, a self-describing object that supplies both directional
binding capabilities through the public Stage Extension API.
