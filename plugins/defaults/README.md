# obst-defaults

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

`obst-defaults` is the explicitly activated first-party plugin for the OBST
Python runtime. It supplies replaceable Stage, stream-profile, Carrier and
Packager capabilities through the same entry-point contracts as third-party
plugins.

It is a separate distribution. Installing it makes the plugin discoverable;
enabling it permits its Python code and contributed commands to run.

```console
python -m pip install ./plugins/defaults
obst plugins enable obst-defaults
obst extensions
```

The plugin contributes:

- Delta8 and two zlib Stage contracts;
- the portable `obst.file@1` stream profile and file adapter;
- typed extraction resources for member count and recovered bytes;
- filesystem, memory and standard-input Carrier capabilities;
- the fixed packaging policy; and
- the `pack` and `unpack` CLI commands.

Start with the [plugin documentation](docs/README.md). The
[OBST documentation](../../docs/README.md) owns the container format and the
public runtime contracts used by this plugin.

## Development

From the repository root:

```console
python -m pip install -e . -e "./plugins/defaults[dev]"
python plugins/defaults/scripts/quality.py
```

The plugin owns its provider tests, conformance vectors and documentation
checks under this directory.

## License

`obst-defaults` is licensed under the
[Mozilla Public License 2.0](LICENSE).
