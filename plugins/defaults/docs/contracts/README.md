# obst-defaults contracts

Parent: [obst-defaults documentation](../README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: CC-BY-ND-4.0
-->

These are the normative, language-neutral contracts for wire-visible
Extensions implemented by `obst-defaults`. They define how another
implementation recovers logical bytes and interprets metadata or parameters;
they do not require use of the Python providers shipped here.

## Stage contracts

See the [Stage contract index](stages/README.md) for Delta8 and both zlib
contracts.

## Stream contracts

See the [stream contract index](streams/README.md) for the portable file
profile.

## Related documentation

The OBST runtime owns the generic [Stage](../../../../docs/toolchain/extension-api/stages.md)
and [stream-profile](../../../../docs/toolchain/extension-api/profiles.md) protocols. The
[format specification](../../../../docs/format.md) defines how Extension IDs
and specification URLs enter a container.
