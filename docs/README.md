# OBST documentation

Parent: [Project README](../README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

OBST and its Python toolchain answer different questions. The format documents
define valid container bytes. The toolchain documents explain how this
repository reads, writes, inspects and extends those bytes.

Start with the [project README](../README.md) for the short introduction. Use
this page when you already know what you want to build or verify.

## Table of contents

- [OBST documentation](#obst-documentation)
	- [Table of contents](#table-of-contents)
	- [Choose a starting point](#choose-a-starting-point)
	- [The OBST format](#the-obst-format)
	- [The Python toolchain](#the-python-toolchain)
	- [Project documentation](#project-documentation)
	- [Status markers](#status-markers)

## Choose a starting point

| Goal                             | Start here                                   |
| -------------------------------- | -------------------------------------------- |
| Understand the container         | [Container anatomy](anatomy.md)              |
| Implement OBST independently     | [Normative format](format.md)                |
| Understand a format decision     | [Design notes](design.md)                    |
| Use the Python API               | [Python toolchain](toolchain/README.md)      |
| Build an Extension or plugin     | [Extension system](toolchain/extensions.md)  |
| Use the command line             | [CLI guide](toolchain/cli.md)                |
| Run interoperability checks      | [Conformance](toolchain/conformance.md)      |
| Understand a failure             | [Runtime errors](toolchain/errors.md)        |
| Package or extract regular files | [`obst-defaults`](../plugins/defaults/docs/) |
| See unfinished work              | [Roadmap](../ROADMAP.md)                     |

## The OBST format

The format side is language-neutral. It does not depend on Python packages,
plugin activation, local resource profiles or a particular Carrier.

| Page                    | Authority                                                |
| ----------------------- | -------------------------------------------------------- |
| [Format](format.md)     | Normative records, validity rules and `obst.bytes@1`     |
| [Anatomy](anatomy.md)   | Non-normative walkthrough of streams, Recipes and chunks |
| [Design](design.md)     | Rationale behind format boundaries and non-goals         |
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

## Status markers

Unmarked prose describes implemented behavior.

> [!NOTE]
> **Future semantics:** The described behavior does not exist. Every such note
> links to a concrete roadmap item.

> [!NOTE]
> **Reserved semantics:** The present contract reserves a value or meaning that
> implementations must not reuse. This does not imply a planned feature.

Maintainers should read
[Writing and maintaining documentation](writing-and-maintaining-docs.md)
before adding or moving documentation.
