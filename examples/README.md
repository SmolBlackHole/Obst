# OBST examples

Parent: [OBST](../README.md)

This directory contains executable examples of the public Python API and
extension packaging boundary. The API walkthrough keeps every byte in memory;
the adaptive-zlib package demonstrates installed-plugin discovery and a
non-trivial Stage without giving example code a privileged path into OBST.

## Table of contents

- [OBST examples](#obst-examples)
	- [Table of contents](#table-of-contents)
	- [Run the API walkthrough](#run-the-api-walkthrough)
	- [What the walkthrough demonstrates](#what-the-walkthrough-demonstrates)
	- [Install the example plugin](#install-the-example-plugin)
	- [Change it](#change-it)

## Run the API walkthrough

Install the checkout once:

```bash
python -m pip install -e . -e ./plugins/defaults
```

The script does not depend on the current working directory. Once OBST is
installed, its absolute path works from anywhere:

```bash
python /path/to/Obst/plugins/defaults/examples/api_walkthrough.py
```

It prints structural counts and finishes with:

```text
Round trip byte-identical: True
```

## What the walkthrough demonstrates

[`api_walkthrough.py`](api_walkthrough.py) follows one complete in-memory flow:

```text
explicit extension registry
    -> fixed recipes and logical byte streams
    -> in-memory OBST container
    -> callback-free structural inspection
    -> trusted chunk decoding
    -> byte-identical logical streams
```

The Delta8 and zlib extensions use the same public registry boundary as a
third-party extension. `BytesIO` is the already opened binary endpoint; no
carrier lifecycle is needed because the example owns the memory directly. The
core never receives a path and writes no file.

Inspection and decoding intentionally use separate `ContainerReader` values.
Each reader is single-consumption, and structural inspection does not execute
payload decoders.

## Install the example plugin

[`plugin_adaptive_zlib/`](plugin_adaptive_zlib/) is a complete Python
distribution with an `obst.extensions` entry point and a self-describing
adaptive Stage:

```console
python -m pip install -e examples/plugin_adaptive_zlib
obst plugins list
obst plugins enable adaptive-zlib
obst extensions
obst plugins test adaptive-zlib
obst adaptive-pack README.md -o readme-adaptive.obst
```

Its encoder tries several byte layouts and preset dictionaries for each chunk;
its decoder follows the recorded choice once. The plugin README owns that Stage
contract, explains the trust boundary and includes an honest comparison against
the existing sample containers. Its command contribution becomes visible only
after `adaptive-zlib` is enabled and needs no capability from `obst-defaults`.

## Change it

Try different payload bytes, chunk sizes or stage combinations. Keep recipes
reversible and keep resource use bounded. The walkthrough raises an error if
the recovered streams differ from the originals, which is considerably more
useful than admiring a container that merely looks plausible.
