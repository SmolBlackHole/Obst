# Contributing to OBST

OBST is experimental, and contributions are welcome. Small fixes can go
straight to a pull request. Please discuss changes to the wire format, public
APIs, trust boundaries, distribution layout or dependency policy before doing
the implementation work.

## Set up the repository

The reference toolchain currently targets Python 3.14.

```bash
python -m venv .venv

# Linux/macOS
. .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install -e ".[dev]" -e ./plugins/defaults -e ./examples/plugin_adaptive_zlib
obst plugins enable obst-defaults
python scripts/quality.py
```

The quality command checks formatting, linting, strict typing, REUSE license
metadata and the test suites owned by all 3 distributions.

## Keep ownership explicit

- [`docs/format.md`](docs/format.md) is the authoritative OBST specification.
- `src/obst/` owns the format implementation and shared Python toolchain.
- `plugins/defaults/` owns the defaults plugin, including its tests and docs.
- `examples/plugin_adaptive_zlib/` owns the complete example plugin.
- Container bytes must never discover, install, enable or load a plugin.
- Plugin-specific code, tests and documentation stay with that plugin. The
  first-party plugin does not get a privileged path.

A wire change normally updates the specification or relevant contract, the
implementation and tests, the conformance generator and corpus, affected
samples or snapshots, and the documentation that describes the changed rule.
Generated conformance vectors should not be edited by hand.

The [documentation guide](docs/writing-and-maintaining-docs.md) explains where
information belongs and which page is authoritative for each kind of claim.

## Pull requests

A useful pull request explains:

- the behavior or ambiguity it changes;
- any wire, public API or trust-boundary effect;
- the checks that passed; and
- known limitations, skipped checks or follow-up work.

Preserve existing SPDX metadata and the license assigned to the file. Format
specifications and normative contracts use CC BY 4.0. Software and general
project documentation use MPL 2.0.

Report vulnerabilities through the private process in
[`SECURITY.md`](SECURITY.md), not through a public issue or pull request.
