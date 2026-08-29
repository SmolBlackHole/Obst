# OBST contract index

Parent: [Documentation index](../README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: CC-BY-ND-4.0
-->

OBST defines its one built-in logical-stream contract directly in the format
specification. Every other wire-visible Extension contract is published and
tested by the distribution that implements it.

## Table of contents

- [OBST contract index](#obst-contract-index)
	- [Table of contents](#table-of-contents)
	- [Built-in contract](#built-in-contract)
	- [Plugin contract catalogs](#plugin-contract-catalogs)

## Built-in contract

- [`obst.bytes@1`](../format.md#obstbytes1-stream-contract): opaque logical
  bytes with empty metadata.

## Plugin contract catalogs

- [`obst-defaults`](../../plugins/defaults/docs/contracts/README.md): Delta8,
  zlib and portable-file contracts.

The [format specification](../format.md) defines how versioned IDs, opaque
parameters, metadata and specification URLs are represented. A plugin contract
defines the meaning needed to decode one such ID.
