# `obst.file@1` stream contract

Parent: [obst-defaults stream contracts](README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: CC-BY-ND-4.0
-->

Status: experimental first-party stream-profile contract.

Contract type: logical stream profile.

One `obst.file@1` stream represents one regular file. This contract describes
logical bytes and portable metadata, not where the containing OBST byte stream
is stored.

## Table of contents

- [`obst.file@1` stream contract](#obstfile1-stream-contract)
	- [Table of contents](#table-of-contents)
	- [Logical bytes](#logical-bytes)
	- [Metadata](#metadata)
	- [Recipes and chunks](#recipes-and-chunks)
	- [Filesystem metadata](#filesystem-metadata)
	- [Inspection](#inspection)
	- [Conformance](#conformance)
	- [Python reference implementation](#python-reference-implementation)

## Logical bytes

The decoded logical stream is the complete file content. Concatenating decoded
chunks in ascending sequence order reconstructs the file byte for byte.

The original size is not repeated in profile metadata. It is the sum of the
stream's declared logical chunk sizes, each of which is verified during decode.

## Metadata

Metadata is exactly one UTF-8 encoded Unicode basename normalized to NFC. The
core stream entry already carries its byte length, so the metadata contains no
additional length prefix.

A conforming basename:

- is between 1 and 255 bytes when encoded as UTF-8;
- is neither `.` nor `..`;
- is a basename, not an absolute or relative path;
- contains no Unicode General Category `Cc` character or any of
  `< > : " / \\ | ? *`;
- contains none of the bidirectional control code points `U+061C`, `U+200E`,
  `U+200F`, `U+202A` through `U+202E`, or `U+2066` through `U+2069`;
- does not end in a space or dot; and
- does not use `AUX`, `CON`, `NUL`, `PRN`, `COM1` through `COM9`, or `LPT1`
  through `LPT9`, including those names with extensions.

For the Windows-reserved-name rule, take the portion before the first `.`,
apply Unicode case folding and compare it with the ASCII names above. The rule
therefore rejects forms such as `con`, `CON.txt` and `Com1.data`.

Other Unicode format characters are not rejected merely because they belong
to General Category `Cf`. For example, a zero-width joiner (`U+200D`) remains
valid when the complete basename satisfies every other rule. Human tooling is
still responsible for escaping terminal controls supplied by any profile.

This version does not pin the Unicode data version used for NFC and case
folding. Implementations using different Unicode tables may disagree on edge
cases whose properties changed between versions.

> [!NOTE]
> **Future semantics:** A pinned Unicode data version does not exist for
> `obst.file@1`. Defining that dependency is tracked in the
> [roadmap](../../../../../ROADMAP.md#now-pre-public-stabilization).

Filename collision comparison uses Unicode case folding after NFC
normalization. Two colliding names do not form a conforming file collection,
even when a host filesystem would accept both. Version 1 leaves the collection
scope unspecified. The first-party Python
[file adapter](../../files/extraction.md#run-extraction) treats all streams in
one pure file container as the collection.

> [!NOTE]
> **Future semantics:** A container-wide portable collision scope does not
> exist for `obst.file@1`. Defining that scope is tracked in the
> [roadmap](../../../../../ROADMAP.md#now-pre-public-stabilization).

## Recipes and chunks

The profile assigns no compression recipe and no chunk size. Producers may use
any valid recipes and chunk boundaries that preserve the logical bytes.

## Filesystem metadata

Version 1 does not represent directory trees, links, timestamps, permissions,
ownership or extended attributes. Those concepts must not be inferred from the
basename metadata.

## Inspection

The first-party metadata interpreter exposes the basename as both the stream
label and the `name` field. Invalid metadata remains authoritative bytes and
produces an interpretation error.

## Conformance

Profile and archiver tests cover UTF-8 and NFC, portable-name rejection,
case-folded archive collisions, exact file bytes and bounded extraction
behavior.

## Python reference implementation

[`plugins/defaults/src/obst_defaults/files/profile.py`](../../../src/obst_defaults/files/profile.py)
provides `FileExtension`, which owns metadata encoding, file sourcing,
materialization and optional interpretation through public extension
capabilities. Its typed Python metadata value is `PortableFileMetadata`;
authoritative wire metadata remains the UTF-8 byte sequence specified above.
[`plugins/defaults/src/obst_defaults/files/adapter.py`](../../../src/obst_defaults/files/adapter.py)
provides `FileArchiver`, which resolves those capabilities by exact
stream-profile ID from the Extension objects selected by its caller.
Filesystem composition is documented separately in
[File profiles](../../files/profiles.md).
