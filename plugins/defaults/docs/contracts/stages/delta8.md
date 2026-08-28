# `obst.delta8@1` stage contract

Parent: [obst-defaults Stage contracts](README.md)

Status: experimental first-party stage contract.

Contract type: reversible, chunk-local byte transform.

`obst.delta8@1` replaces each byte with its modulo-256 difference from the
preceding logical byte in the same chunk.

## Table of contents

- [`obst.delta8@1` stage contract](#obstdelta81-stage-contract)
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

The logical input and encoded output are arbitrary finite byte strings of equal
length. Each encoded byte records one modulo-256 difference inside its chunk.

## Parameters

The parameter byte string is empty. Any non-empty value is invalid.

## Forward operation

Let the input bytes be `x[0]` through `x[n-1]`. The encoded bytes `y` are:

```text
y[0] = x[0]
y[i] = (x[i] - x[i-1]) mod 256, for i > 0
```

An empty input produces an empty output.

## Inverse operation

Let the encoded bytes be `y[0]` through `y[n-1]`. The logical bytes `x` are:

```text
x[0] = y[0]
x[i] = (x[i-1] + y[i]) mod 256, for i > 0
```

An empty input produces an empty output.

## Chunk boundaries and state

The previous value starts at zero for every chunk. State never crosses a chunk
boundary, so splitting the same logical byte sequence at different boundaries
may change its encoded representation without changing the recovered bytes.

## Invalid inputs

Only non-empty parameters are invalid. Every encoded byte string is otherwise
a valid Delta8 payload.

## Resource behavior

Both directions preserve length and require output space equal to the input
length. An implementation must reject an operation whose output would exceed
the caller's configured output limit.

## Inspection

There are no parameters to interpret.

## Conformance

The following known answers use hexadecimal byte strings:

| Logical bytes | Encoded bytes |
| ------------- | ------------- |
| empty         | empty         |
| `00`          | `00`          |
| `00 01 ff`    | `00 01 fe`    |

Processing `01` and `02` as separate chunks yields `01` and `02`; processing
`01 02` as one chunk yields `01 01`. Conformance tests also cover varied
inputs, exact round-trips, parameter rejection and output limits.

## Python reference implementation

[`plugins/defaults/src/obst_defaults/transforms/delta8.py`](../../../src/obst_defaults/transforms/delta8.py)
provides `Delta8Extension`, a self-describing object that supplies both
directional binding capabilities through the public Stage Extension API.
