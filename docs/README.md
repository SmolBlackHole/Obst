# OBST documentation

Parent: [Project README](../README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

OBST and its Python toolchain answer different questions. The format documents
define valid container bytes. The toolchain documents explain how this
repository reads, writes, inspects and extends those bytes.

Start with the [project README](../README.md) for the introduction and a first
CLI experiment. Then choose a path below. You can use existing tooling, write
one capability or implement the wire format without working through every
other part of the ecosystem.

## Table of contents

- [OBST documentation](#obst-documentation)
	- [Table of contents](#table-of-contents)
	- [Choose a starting point](#choose-a-starting-point)
	- [Read it as a book](#read-it-as-a-book)
	- [The OBST format](#the-obst-format)
	- [The Python toolchain](#the-python-toolchain)
	- [Project documentation](#project-documentation)
	- [Status markers](#status-markers)

## Choose a starting point

| I want to ... | Start here | Continue when needed |
| ------------- | ---------- | -------------------- |
| Understand OBST | [Anatomy](anatomy.md) | [Design](design.md) explains the boundaries |
| Explore possible applications | [Eldritch horrors](eldritch_horrors.md) | Each construction links to its mechanism or example |
| Pack files or inspect containers | [CLI](toolchain/cli.md) and [defaults](../plugins/defaults/docs/README.md) | [Output reference](toolchain/cli-output-reference.md) and [errors](toolchain/errors.md) |
| Integrate OBST into Python | [Toolchain introduction](toolchain/README.md) | [Reading](toolchain/reading.md) and [writing](toolchain/writing.md) |
| Define a stream profile or Stage | [Contract identity and ownership](design.md#recipes-and-contract-identity) | [Extension interfaces](toolchain/extensions.md), [examples](../examples/README.md) and [conformance](toolchain/conformance.md) |
| Connect storage or choose encoding policy | [Carriers](toolchain/extension-api/carriers.md) or [Packagers](toolchain/extension-api/packagers.md) | [Resources](toolchain/resources.md) and [plugin distribution](toolchain/plugins.md) |
| Implement a reader or writer independently | [Wire specification](format.md) | Required [Extension contracts](contracts/README.md) and [portable format corpus](toolchain/conformance.md#format-corpus) |
| Look up an exact rule | [Wire specification](format.md), [contracts](contracts/README.md) or [Python guides](toolchain/README.md#choose-a-guide) | Read the authority for that layer directly |
| Assess unfinished work | [Roadmap](../ROADMAP.md) | [What remains unproven](toolchain/conformance.md#what-remains-unproven) |

Independent implementations do not need the Python plugin manager. A Carrier
author does not need to implement a Stage. File users can start with the CLI.
The paths meet where they share a contract, not at a mandatory setup sequence.

## Read it as a book

For a guided introduction, follow this sequence:

1. [Project README](../README.md): what OBST is, a first experiment and whether it fits.
2. [Anatomy](anatomy.md): follow logical bytes into a container and back out.
3. [Design](design.md): why meaning, representation and runtime policy have separate owners.
4. [Eldritch horrors](eldritch_horrors.md): build larger constructions from those rules.
5. Choose a working path: [use the Python toolchain](toolchain/README.md),
   [provide a capability](toolchain/extensions.md), or [implement the wire contract](format.md).

The catalogs below are the reference shelves. They remain directly accessible;
reading the introductory chapters is optional when you already know your task.

## The OBST format

The format side is language-neutral. It does not depend on Python packages,
plugin activation, local resource profiles or a particular Carrier.

| Page                    | Authority                                                |
| ----------------------- | -------------------------------------------------------- |
| [Format](format.md)     | Normative records, validity rules and `obst.bytes@1`     |
| [Anatomy](anatomy.md)   | Non-normative walkthrough of streams, Recipes and chunks |
| [Design](design.md)     | Rationale behind format boundaries and non-goals         |
| [Eldritch horrors](eldritch_horrors.md) | Application patterns built from the existing boundaries |
| [Contracts](contracts/) | Independently versioned, wire-visible contract catalog   |

`format.md` is the sole authority for whether a byte stream conforms to OBST.
The other pages explain it or route to independent Extension contracts.

## The Python toolchain

The [toolchain index](toolchain/README.md) owns the reference implementation's
public boundary and navigation.

| Page                                    | Contents                                                |
| --------------------------------------- | ------------------------------------------------------- |
| [Reading](toolchain/reading.md)         | Structural parsing and logical decoding                 |
| [Writing](toolchain/writing.md)         | Low-level writing and packaging entry points            |
| [Inspection](toolchain/inspection.md)   | Renderer-neutral structure and capability reports       |
| [Resources](toolchain/resources.md)     | Typed local ceilings, profiles and operation accounting |
| [Extensions](toolchain/extensions.md)   | Capability taxonomy, composition and provider APIs      |
| [Plugins](toolchain/plugins.md)         | Inert discovery, explicit activation and trust boundary |
| [CLI](toolchain/cli.md)                 | Native commands, plugin-host behavior and output modes  |
| [Errors](toolchain/errors.md)           | Python exceptions, CLI error kinds and exit codes       |
| [Conformance](toolchain/conformance.md) | Portable corpus schema, provider suites and runner API  |

Detailed wire mappings, Recipe execution, packaging internals and individual
Extension protocols sit below those entry pages. They remain toolchain
documentation even when they describe language-neutral contracts consumed by
Python providers.

## Project documentation

| Page                                                            | Contents                              |
| --------------------------------------------------------------- | ------------------------------------- |
| [Writing and maintaining docs](writing-and-maintaining-docs.md) | Authority, structure and review rules |
| [Roadmap](../ROADMAP.md)                                        | Unfinished work and delivery order    |
| [Contributing](../CONTRIBUTING.md)                              | Setup, ownership and pull requests    |
| [How this happened](../README.md#how-this-happened)              | Shelly measurements, recursive fruit and the name |
| [Security](../SECURITY.md)                                      | Reporting and plugin trust boundary   |

## Status markers

Behavior descriptions refer to implemented behavior unless marked otherwise.
Explicit design goals and application constructions, such as the Horrors,
describe intent or possible composition, not shipped applications.

> [!NOTE]
> **Future semantics:** The described behavior does not exist. Every such note
> links to a concrete roadmap item.

> [!NOTE]
> **Reserved semantics:** The present contract reserves a value or meaning that
> implementations must not reuse. This does not imply a planned feature.

Maintainers should read
[Writing and maintaining documentation](writing-and-maintaining-docs.md)
before adding or moving documentation.
