# obst-defaults documentation

Parent: [obst-defaults](../README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

This documentation describes only the capabilities supplied by the
`obst-defaults` distribution. The OBST project documentation remains
authoritative for the byte format, public runtime protocols, plugin trust
boundary and generic Extension behavior.

## Part I: understand obst-defaults

- [Codecs](codecs.md): zlib providers and parameter authoring.
- [Transforms](transforms.md): the Delta8 provider and multi-Stage
  composition.
- [Portable files](files/README.md): profile capabilities, file sources and
  safe extraction.

## Part II: contracts

- [Contract index](contracts/README.md): normative decoding contracts for the
  wire-visible Extensions supplied here.

## Part III: runtime capabilities

- [Carriers](carriers/README.md): filesystem, memory and standard-input
  endpoints.
- [Packagers](packagers/README.md): the fixed packaging policy.
- [File resource accounting](files/extraction.md#resource-accounting): typed member and
  recovered-byte ceilings contributed through `obst.resources`.

## Part IV: use and verify the tooling

- [Command-line guide](cli.md): activate the plugin, then use its `pack` and
  `unpack` commands.
- [Plugin-owned errors](errors.md): failures and exit codes contributed by
  these commands and providers.
- [Conformance](conformance.md): package-owned vectors, generation and
  coverage.

## OBST runtime references

- [OBST documentation](../../../docs/README.md)
- [Extension protocols](../../../docs/toolchain/extensions.md)
- [Plugin loading and trust](../../../docs/toolchain/plugins.md)
- [Format specification](../../../docs/format.md)
