# `obst.zlib@2` stage contract

Parent: [Normative contracts](../../README.md#normative-contracts)

Status: experimental first-party stage contract.

Contract type: reversible, chunk-local compression codec.

`obst.zlib@2` stores one complete
[RFC 1950 zlib](https://www.rfc-editor.org/rfc/rfc1950) stream using a preset
dictionary carried in the recipe's Stage parameters. The dictionary is
therefore available before the first payload chunk arrives.

## Table of contents

- [`obst.zlib@2` stage contract](#obstzlib2-stage-contract)
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
exactly one complete RFC 1950 zlib stream that requires the preset dictionary
carried in the Stage parameters.

## Parameters

The parameter byte string is:

| Offset | Size       | Type  | Field             |
| -----: | ---------- | ----- | ----------------- |
|      0 | 1          | u8    | compression level |
|      1 | 1 to 32768 | bytes | preset dictionary |

The compression level is an integer from `0` through `9`, inclusive. The
dictionary contains at least 1 and at most 32768 bytes. Any other parameter
length or compression-level value is invalid.

The level is an encoder effort hint. A conforming encoder accepts all 10 values
and may map them to the closest settings exposed by its compression backend.
The dictionary bytes are authoritative and are not text, an identifier or a
reference to external state.

The contract does not require bit-identical encoder output, monotonic encoded
sizes or one specific zlib implementation. Different compliant encoders may
produce different valid zlib byte strings for the same logical input, level
and dictionary.

## Contract identity

`@2` identifies this language-neutral preset-dictionary byte contract. It does
not identify a Python package, provider release, linked libz version or
compression backend.

Any provider registered as `obst.zlib@2` must decode every valid stream in this
contract. A provider that cannot supply the parameter dictionary to its
backend must not claim the decoder capability. Provider and runtime versions
are diagnostics, not substitutes for a new Stage ID.

`obst.zlib@2` does not replace [`obst.zlib@1`](zlib.md). `@1` requires
dictionary-free streams, while `@2` requires a preset dictionary.

## Forward operation

The encoder compresses the complete logical chunk into exactly one complete
zlib stream using the declared level and the exact parameter dictionary. The
RFC 1950 `FDICT` flag must be `1`, and the big-endian `DICTID` must equal the
Adler-32 of the complete dictionary bytes.

No bytes precede or follow the zlib stream in the stage output.

## Inverse operation

The decoder validates `FDICT`, validates `DICTID` against the parameter
dictionary and uses that exact dictionary to recover the logical bytes. It
rejects:

- invalid zlib or DEFLATE framing;
- a stream whose RFC 1950 `FDICT` flag is `0`;
- a `DICTID` that does not match the parameter dictionary;
- an incomplete zlib stream;
- bytes following the completed zlib stream; and
- output exceeding the caller's configured limit.

## Chunk boundaries and state

Every chunk is a separate zlib stream. Compressor and decompressor state never
crosses a chunk boundary. The same Stage parameters, including the dictionary,
apply independently to every chunk using that recipe.

Empty logical input is valid and still produces a complete dictionary-bearing
zlib stream.

## Resource behavior

Both directions receive an output-size limit from the caller. They must stop
and reject the operation if the produced byte string would exceed a finite
limit. Manifest and parameter-size limits apply before a provider receives the
dictionary.

The dictionary is ordinary container data. It is not confidential, executable
or fetched from its contents.

## Inspection

An inspector that interprets the parameters exposes `compression_level`,
`dictionary_size` and the dictionary's 8-digit lowercase
`dictionary_adler32`. The raw parameter bytes remain authoritative.

## Conformance

A conforming implementation tests all compression levels, dictionary-size
boundaries, empty input, varied binary inputs, dictionary-bearing headers,
wrong dictionaries, dictionary-free streams, incomplete or trailing streams,
output limits and exact round-trips. Encoded bytes need not match another
conforming encoder byte for byte.

A conforming implementation must not depend on the Python reference provider
or on the provider version that created a container.

## Python reference implementation

[`plugins/defaults/src/obst_defaults/codecs/zlib.py`](../../../plugins/defaults/src/obst_defaults/codecs/zlib.py)
provides `ZlibDictionaryExtension`, a self-describing object that supplies
parameter authoring, both directional binding capabilities and optional
parameter interpretation through the public Stage Extension API.
The [codec guide](../../extensions/codecs.md) owns the Python authoring example.
