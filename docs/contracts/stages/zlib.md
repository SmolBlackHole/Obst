# `obst.zlib@1` stage contract

Parent: [Normative contracts](../../README.md#normative-contracts)

Status: experimental first-party stage contract.

Contract type: reversible, chunk-local compression codec.

`obst.zlib@1` stores one complete, dictionary-free
[RFC 1950 zlib](https://www.rfc-editor.org/rfc/rfc1950) stream whose compressed
data uses [RFC 1951 DEFLATE](https://www.rfc-editor.org/rfc/rfc1951). Preset
dictionaries belong to the separate [`obst.zlib@2`](zlib-dictionary.md)
contract.

## Table of contents

- [`obst.zlib@1` stage contract](#obstzlib1-stage-contract)
	- [Table of contents](#table-of-contents)
	- [Logical input and output](#logical-input-and-output)
	- [Parameters](#parameters)
	- [Contract identity](#contract-identity)
	- [Forward operation](#forward-operation)
	- [Inverse operation](#inverse-operation)
	- [Chunk boundaries and state](#chunk-boundaries-and-state)
	- [Resource behavior](#resource-behavior)
	- [Inspection](#inspection)
	- [Conformance](#conformance)
	- [Python reference implementation](#python-reference-implementation)

## Logical input and output

The logical input is an arbitrary finite byte string. The encoded output is
exactly one complete dictionary-free RFC 1950 zlib stream.

## Parameters

The parameter byte string contains exactly one unsigned byte. Its value is an
encoder compression level from `0` through `9`, inclusive.

Any other parameter length or value is invalid.

The level is an encoder effort hint. A conforming encoder accepts all 10 values
and may map them to the closest settings exposed by its compression backend. A
decoder validates the byte but does not infer or verify which effort produced
the encoded stream.

The contract does not require bit-identical encoder output, monotonic encoded
sizes or one specific zlib implementation. Different compliant encoders may
produce different valid zlib byte strings for the same logical input and
level.

## Contract identity

`@1` identifies this language-neutral dictionary-free byte contract. It does
not identify a Python package, provider release, linked libz version or
compression backend.

Any provider registered as `obst.zlib@1` must decode every valid stream in this
contract. Provider and runtime versions are diagnostics, not substitutes for a
new Stage ID.

## Forward operation

The encoder compresses the complete logical chunk into exactly one complete
zlib stream using the declared level. The RFC 1950 `FDICT` flag must be `0`.
No bytes precede or follow that stream in the stage output.

## Inverse operation

The decoder consumes exactly one complete zlib stream and returns its
uncompressed bytes. It rejects:

- invalid zlib or DEFLATE framing;
- a stream whose RFC 1950 `FDICT` flag is `1`;
- an incomplete zlib stream;
- bytes following the completed zlib stream; and
- output exceeding the caller's configured limit.

## Chunk boundaries and state

Every chunk is a separate zlib stream. Compressor and decompressor state never
crosses a chunk boundary. Empty logical input is valid and still produces a
complete zlib stream.

## Resource behavior

Both directions receive an output-size limit from the caller. They must stop
and reject the operation if the produced byte string would exceed a finite
limit. The Python reference encoder checks incremental compressor output instead
of materializing an over-limit result first.

## Inspection

An inspector that interprets the parameters exposes the byte as
`compression_level`. Invalid parameters remain authoritative bytes and produce
an interpretation error.

## Conformance

A conforming implementation tests levels `0` through `9`, empty input, varied
binary inputs, invalid framing, incomplete streams, trailing or concatenated
streams, preset-dictionary rejection, output limits and exact round-trips.
Encoded bytes need not match another conforming encoder byte for byte.

## Python reference implementation

[`plugins/defaults/src/obst_defaults/codecs/zlib.py`](../../../plugins/defaults/src/obst_defaults/codecs/zlib.py)
provides `ZlibExtension`, a self-describing object that supplies parameter
authoring, both directional binding capabilities and optional parameter
interpretation through the public Stage Extension API.
The [codec guide](../../extensions/codecs.md) owns the Python authoring example.
