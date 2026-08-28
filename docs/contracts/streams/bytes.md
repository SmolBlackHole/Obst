# `obst.bytes@1` stream contract

Parent: [OBST contract index](../README.md)

Status: experimental core stream contract.

Contract type: logical stream profile.

`obst.bytes@1` identifies one opaque logical byte sequence. It is the only
stream contract defined by the core.

## Table of contents

- [`obst.bytes@1` stream contract](#obstbytes1-stream-contract)
	- [Table of contents](#table-of-contents)
	- [Logical bytes](#logical-bytes)
	- [Metadata](#metadata)
	- [Empty streams](#empty-streams)
	- [Inspection](#inspection)
	- [Conformance](#conformance)
	- [Python reference implementation](#python-reference-implementation)

## Logical bytes

Concatenating the decoded chunks in ascending sequence order reconstructs the
logical byte sequence. Chunk boundaries carry no additional meaning.

Any valid recipe may represent a chunk as long as its inverse recovers the
exact logical bytes required by the container's size and hash fields.

## Metadata

The metadata byte string is empty. A producer that writes non-empty metadata
does not conform to `obst.bytes@1`.

The core may still preserve such metadata as opaque bytes. Structural container
validity and profile conformance are separate questions.

## Empty streams

A declaration with no chunks represents an empty logical byte sequence.

## Inspection

The core reports the stream ID, type, raw metadata, declared default recipe,
actual recipe usage and aggregate chunk sizes. It assigns no semantic label to
the bytes.

## Conformance

Core tests cover empty and multi-chunk byte streams, interleaving, recipe
execution and byte-exact reconstruction.

## Python reference implementation

The identifier is defined in
[`src/obst/core/model.py`](../../../src/obst/core/model.py). The generic
reader and logical decoding operations implement reconstruction without a
special profile provider or registry entry.
