# obst-defaults conformance

Parent: [obst-defaults documentation](README.md)

This distribution owns a static, portable conformance suite for every
wire-visible contract it implements. The suite is package data and is exposed
through the ordinary `obst.conformance` plugin entry point.

## Table of contents

- [obst-defaults conformance](#obst-defaults-conformance)
	- [Table of contents](#table-of-contents)
	- [Coverage](#coverage)
	- [Run the suite](#run-the-suite)
	- [Regenerate the vectors](#regenerate-the-vectors)
	- [Boundary](#boundary)

## Coverage

The catalog covers known logical and encoded Stage bytes, canonical parameter
bytes, malformed parameters and payloads, output ceilings, portable file
metadata, rejected filenames and complete logical recovery cases. Ordinary
plugin tests add implementation-specific coverage such as all declared zlib
levels, concurrent calls and filesystem publication behavior.

The decode-only Delta8 plus zlib case fixes one valid multi-chunk
representation. It does not require every conforming zlib encoder to produce
identical compressed bytes.

## Run the suite

```console
obst plugins test obst-defaults
```

This explicitly loads and executes installed plugin code with the current
process privileges. It is not a sandbox. Test only plugins you trust.

Portable consumers can load the bundled JSON without plugin discovery through
the public `obst.conformance` catalog API.

## Regenerate the vectors

From the repository root:

```console
python plugins/defaults/scripts/build_conformance.py
```

The generator writes only
`plugins/defaults/src/obst_defaults/conformance_vectors/index.json`. The
plugin's tests verify that regeneration is byte-identical.

## Boundary

The suite establishes the behavior of this distribution's wire-visible
providers. Runtime-only Carriers and Packagers have no wire vectors; their
request, lifecycle and publication behavior belongs to ordinary tests under
`plugins/defaults/tests`.

The root [conformance guide](../../../docs/conformance.md) owns the catalog
schema, public runner API, format corpus and interoperability evidence.
