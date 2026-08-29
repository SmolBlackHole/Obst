# obst-defaults Packagers

Parent: [obst-defaults documentation](../README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

Packagers are runtime policies that prepare a valid OBST write operation from
logical sources. They are selected by the host and are never named by
container bytes.

## Available policy

- [`obst.fixed@1`](fixed.md): package every source once with its declared
  Recipe.

## Shared contract

The OBST runtime owns the generic [Packager provider
contract](../../../../docs/toolchain/extension-api/packagers.md) and [packaging
API](../../../../docs/toolchain/internals/packaging.md).
