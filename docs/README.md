# OBST documentation

Parent: [Project README](../README.md)

OBST is a self-describing, streamable representation layer for logical byte
streams, between domain formats and storage or transport. This directory maps
the format, reference API, extensions and supporting project documentation.
Start with the [project README](../README.md) if you have not met the fruit yet.

## Table of contents

- [OBST documentation](#obst-documentation)
	- [Table of contents](#table-of-contents)
	- [I want to... (break free)](#i-want-to-break-free)
	- [Documentation by layer](#documentation-by-layer)
		- [Concepts and format](#concepts-and-format)
		- [Python core](#python-core)
		- [Extensions and adapters](#extensions-and-adapters)
		- [Normative contracts](#normative-contracts)
		- [Project support](#project-support)
	- [Status markers](#status-markers)

## I want to... (break free)

| Read                                                               | To                                   |
| ------------------------------------------------------------------ | ------------------------------------ |
| [Anatomy of an OBST container](anatomy.md)                         | understand the container             |
| [Binary format](format.md) and [contracts](contracts/)             | implement a reader or writer         |
| [CLI installation guide](cli.md#install-and-identify-the-format)   | install the Python packages          |
| [Conformance](conformance.md) and [format corpus](../src/obst/conformance/corpus/) | check independent interoperability |
| [Core API](core/)                                                  | use the Python library               |
| [Extension system](extensions/)                                    | build or ship an extension           |
| [Portable file adapter](extensions/files.md)                       | package or extract regular files     |
| [CLI guide](cli.md)                                                | use the command line                 |
| [Runtime errors](errors.md)                                        | understand a failure or exit code    |
| [Design notes](design.md)                                          | understand an architectural decision |
| [Roadmap](../ROADMAP.md)                                           | see unfinished work                  |

## Documentation by layer

### Concepts and format

| Page                             | Contents                                                                       |
| -------------------------------- | ------------------------------------------------------------------------------ |
| [Anatomy](anatomy.md)            | Conceptual relationship between headers, manifest, streams, recipes and chunks |
| [Binary format](format.md)       | Normative framing, fields, limits and validation rules                         |
| [Conformance](conformance.md)    | Independent reconstruction evidence and coverage boundaries                    |
| [Format corpus](../src/obst/conformance/corpus/) | Valid and invalid language-neutral container cases                  |
| [Design](design.md)              | Rationale for implemented architecture and ownership boundaries                |
| [CLI](cli.md)                    | Commands, output modes and filesystem safety                                   |
| [Runtime errors](errors.md)      | Python exceptions, CLI error kinds, exit codes and negative examples           |

### Python core

| Page                                   | Contents                                                          |
| -------------------------------------- | ----------------------------------------------------------------- |
| [Core index](core/README.md)           | Public import boundary and navigation                             |
| [Extension registry](core/registry.md) | Trusted capability composition and immutable lookup               |
| [Wire mapping](core/wire.md)           | Python scalar descriptors, record layouts and CRC framing         |
| [Reading](core/reading.md)             | Structural parsing and logical decoding                           |
| [Writing](core/writing.md)             | Low-level manifest and chunk serialization                        |
| [Recipes and chunks](core/recipes.md)  | Direct pipeline execution, chunk integrity and manifest preflight |
| [Inspection](core/inspection.md)       | Renderer-neutral reports and capability provenance                |
| [Packaging](core/packaging.md)         | Logical sources, package-operation contracts and result values    |
| [Resource limits](core/resources.md)   | Shared local policy, defaults, accounting and refusal semantics   |

### Extensions and adapters

| Page                                    | Contents                                                        |
| --------------------------------------- | --------------------------------------------------------------- |
| [Extension index](extensions/README.md) | Taxonomy, import boundaries and explicit composition            |
| [Stages](extensions/stages.md)          | Self-describing providers, binding, limits and interpretation   |
| [Codecs](extensions/codecs.md)          | Compression-oriented stages and first-party codecs              |
| [Transforms](extensions/transforms.md)  | Reversible preprocessing and the Delta8 transform               |
| [Profiles](extensions/profiles.md)      | Logical semantics, metadata and profile interpretation          |
| [Portable files](extensions/files.md)   | `FileExtension`, file packaging and bounded extraction          |
| [Carriers](extensions/carriers.md)      | Reader, streaming-writer and transactional-publisher lifecycles |
| [Packagers](extensions/packagers.md)    | Replaceable policy for constructing complete containers         |
| [Archivers](extensions/archivers.md)    | General domain-to-stream application-adapter pattern            |
| [Plugins](extensions/plugins.md)        | Opt-in package discovery, factories and trust boundary          |

### Normative contracts

| Contract                                                                           | ID              |
| ---------------------------------------------------------------------------------- | --------------- |
| [Opaque byte streams](contracts/streams/bytes.md)                                  | `obst.bytes@1`  |
| [Portable files](contracts/streams/file.md)                                        | `obst.file@1`   |
| [RAW identity stage](contracts/stages/raw.md)                                      | `obst.raw@1`    |
| [Modulo-256 delta transform](contracts/stages/delta8.md)                           | `obst.delta8@1` |
| [Dictionary-free zlib-wrapped DEFLATE](contracts/stages/zlib.md)                   | `obst.zlib@1`   |
| [zlib-wrapped DEFLATE with preset dictionary](contracts/stages/zlib-dictionary.md) | `obst.zlib@2`   |

### Project support

| Page                                                            | Contents                                              |
| --------------------------------------------------------------- | ----------------------------------------------------- |
| [Writing and maintaining docs](writing-and-maintaining-docs.md) | Authority, status and maintenance rules |
| [Roadmap](../ROADMAP.md)                                        | Unfinished work and delivery order      |

`format.md` and `contracts/` define bytes. API guides explain the Python
reference implementation. `design.md` explains why the implemented boundaries
exist. The roadmap alone owns unfinished work.

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
