# Extension plugins and the plugin manager

Parent: [Extension system](README.md)

An OBST Python plugin is one named set of contributions from an installed
distribution. It may provide ordinary Extensions, CLI commands, resource
policy and portable conformance cases. The public `PluginManager` discovers
those contributions,
stores the host's enabled set and builds immutable operation-local runtimes.
Discovery and activation never import plugin code; loading remains an explicit
host decision, and container bytes never participate in it.

## Trust boundary

> [!WARNING]
> Loading or testing a plugin executes installed third-party Python code with
> the current process privileges. OBST cannot sandbox or guarantee that code.
> Enable only distributions you trust, and use process isolation when that
> trust is insufficient.

An unknown Stage ID in a manifest remains a missing capability. The reader does
not search entry points, import a matching module, fetch a specification URL or
change activation state. This invariant remains exact:

```text
Untrusted OBST bytes alone never acquire or execute new code.
```

## Table of contents

- [Extension plugins and the plugin manager](#extension-plugins-and-the-plugin-manager)
	- [Trust boundary](#trust-boundary)
	- [Table of contents](#table-of-contents)
	- [Identity and ownership](#identity-and-ownership)
	- [Package layout and installation choices](#package-layout-and-installation-choices)
	- [Publish a plugin](#publish-a-plugin)
		- [Extension contribution](#extension-contribution)
		- [Command contribution](#command-contribution)
		- [Resource contributions](#resource-contributions)
		- [Conformance contribution](#conformance-contribution)
	- [Discover and inspect without loading](#discover-and-inspect-without-loading)
	- [Enable, disable and load](#enable-disable-and-load)
	- [Run published conformance cases](#run-published-conformance-cases)
	- [CLI workflow](#cli-workflow)
	- [Conflicts and dependencies](#conflicts-and-dependencies)
	- [Direct composition remains public](#direct-composition-remains-public)

## Identity and ownership

A distribution, plugin, Extension and command are separate identities:

```text
Python distribution: obst-example-adaptive-zlib 0.1.0
    -> plugin name: adaptive-zlib
        -> Extension ID: org.example/adaptive-zlib@1
        -> command name: adaptive-pack
```

The distribution is a Python packaging unit. The plugin name joins matching
entry-point contributions and is local to the Python host. Versioned Extension
IDs identify runtime capabilities; only Stage and stream-profile IDs may enter
OBST manifests. Command names belong to the generic CLI host and never enter
container bytes. Containers never name distributions, plugins or commands.

A plugin name is discovered when one distribution publishes at least one
contribution under `obst.extensions`, `obst.commands`, `obst.resources` or
`obst.conformance`. Command-only and conformance-only plugins need no Extension
contribution. Resource contributions do: every resource and profile ID must be
qualified by an Extension ID returned by the same plugin. A distribution may
publish at most one contribution under the same plugin name in each group, and
matching contributions must come from the same physical distribution. One
extension factory may return several Stage, stream-profile, carrier and
packager Extensions; one command factory may return several commands.

## Package layout and installation choices

The [design notes](../design.md#python-distributions-and-activation) own the
repository's distribution split and the reason installation never implies
activation. After installing `obst-defaults`, the host explicitly enables it:

```console
obst plugins enable obst-defaults
```

That activation makes the first-party Extensions plus `pack` and `unpack`
available. Native `inspect` is already part of `obst`. Installing a wheel alone
never expands the set of code trusted by an operation.

`obst-defaults` declares the same `obst.extensions`, `obst.commands`,
`obst.resources` and `obst.conformance` entry-point groups described below.
The manager has no
first-party import, fallback activation or bundled-provider path.

## Publish a plugin

### Extension contribution

Declare one canonical lowercase name in `pyproject.toml`:

```toml
[project.entry-points."obst.extensions"]
example = "org_example_obst:obst_extensions"
```

The target is a zero-argument callable returning a non-empty exact tuple of
ordinary Extension values:

```python
from obst.core import Extension

from .table import TableExtension
from .weird import WeirdCodecExtension


def obst_extensions() -> tuple[Extension, ...]:
    return (TableExtension(), WeirdCodecExtension())
```

Every returned object passes through the same
[`ExtensionRegistry`](../core/registry.md) validation as directly imported
Extension objects from `obst_defaults` or a third-party package. The plugin
factory is not a second provider API and receives no privileged registration
path.

Plugin names contain 1 to 128 lowercase ASCII letters, digits, `.`, `_` or
`-`, and begin and end with a letter or digit. Names are matched exactly.

### Command contribution

A plugin publishes host-facing commands under the same plugin name:

```toml
[project.entry-points."obst.commands"]
example = "org_example_obst:obst_commands"
```

The factory returns a non-empty exact tuple of structural `CliCommand` values:

```python
import argparse

from obst.cli import (
    CliCommand,
    CliContext,
    HumanOutputStyle,
    escape_human_text,
)


class ExplainCommand:
    name = "explain-example"
    summary = "print one value through an example plugin command"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("value")

    def run(self, args: argparse.Namespace, context: CliContext) -> int:
        style = HumanOutputStyle.for_stream(context.stdout)
        value = style.contributed(escape_human_text(args.value))
        context.stdout.write(f"{value}\n")
        return 0


def obst_commands() -> tuple[CliCommand, ...]:
    return (ExplainCommand(),)
```

`CliContext` supplies the already composed immutable registry, selected plugin
names, standard endpoints and the operation's `ResourceAccounting`. It contains
no first-party IDs or implementation objects. The generic host owns `inspect`, `help`, `plugins`,
`extensions`, `limits` and version output. Contributed command factories execute only
for persistently enabled plugins when their parser is needed. The host captures
the validated name, summary and bound callbacks once; the same immutable
snapshot configures and executes the command. A command must return an exact
integer in `0..255`.

`HumanOutputStyle.for_stream()` gives every contributed command the same
TTY-aware policy as the host. `contributed()` marks both first-party and
third-party contributions consistently; `render_human_table()` aligns compact
tabular output without counting ANSI sequences. Redirected output remains
plain and honors `NO_COLOR`; `escape_human_text()` must still be applied to
untrusted labels before styling them.

### Resource contributions

A plugin that measures work outside the Core resource set publishes those
definitions under the same plugin name:

```toml
[project.entry-points."obst.resources"]
example = "org_example_obst:obst_resources"
```

The factory returns one exact `ResourceContribution`. Resource definitions
carry their typed identity, `ResourceUnit`, `ResourceAggregation`, default
maximum and summary.
Profiles contain only overrides:

```python
from obst.resources import (
    LimitProfile,
    ResourceAggregation,
    ResourceContribution,
    ResourceDefinition,
    ResourceKind,
    ResourceUnit,
)


class ExampleResource(ResourceKind):
    RECORDS = ResourceDefinition(
        "org.example/table@1/records",
        100_000,
        "Records processed by one table operation.",
        ResourceUnit.COUNT,
        ResourceAggregation.TOTAL,
    )


def obst_resources() -> ResourceContribution:
    strict = LimitProfile(
        "org.example/table@1/strict",
        "Smaller limits for untrusted table inputs.",
        ((ExampleResource.RECORDS, 10_000),),
    )
    return ResourceContribution(tuple(ExampleResource), (strict,))
```

`org.example/table@1` must also be an Extension returned by this plugin's
`obst.extensions` factory. The manager composes all selected contributions,
rejects duplicate IDs and validates profile references after the complete
resource catalog exists.

Discovery remains inert. A resource factory runs only when its plugin is
enabled or selected for one operation. Enabling the plugin makes its resources
and profiles available; it never selects a profile. The host chooses a profile
explicitly through `ResourceCatalog.policy()` or
[`obst limits use`](../cli.md#resource-limit-profiles). Unknown overrides kept
in local state do not activate the missing plugin.

### Conformance contribution

A distribution may publish a portable suite under a plugin name:

```toml
[project.entry-points."obst.conformance"]
example = "org_example_obst:obst_conformance"
```

The factory loads one exact `ConformanceSuite` from package resources:

```python
from importlib.resources import files

from obst.conformance import ConformanceSuite, load_conformance_suite


def obst_conformance() -> ConformanceSuite:
    return load_conformance_suite(
        files("org_example_obst").joinpath("conformance_vectors")
    )
```

The package includes one `conformance_vectors/index.json`. The shared
[conformance guide](../conformance.md#plugin-extension-suites) owns the catalog
schema, portable case kinds and public load, write and run APIs.

The `obst.extensions`, `obst.commands`, `obst.resources` and
`obst.conformance` contributions are separate entry points. A format corpus
may therefore be conformance-only, while a
runtime-only carrier or packager needs no meaningless wire suite. When one
plugin name contributes both a suite and wire-visible Stage or stream-profile
providers, the runner requires positive coverage for every such provider. The
distribution owns that generator, its artifacts and its ordinary
implementation tests. Runtime lifecycle behavior remains in the
distribution's ordinary tests. A suite may also include a complete container
case that exercises explicitly supplied dependencies through wire-visible
contracts.

The selected plugin name remains entry-point and CLI context; it is not stored
inside the suite. Discovery stays inert. Loading the factory and exercising
providers executes installed code with the current process privileges, so a
conformance test is not a sandbox.

## Discover and inspect without loading

`PluginManager.discover()` reads all 4 entry-point groups and standard package
metadata without importing their target modules:

```python
from obst.plugins import PluginManager

manager = PluginManager.discover()

for plugin in manager.catalog():
    print(plugin.name, plugin.installed, plugin.enabled)
```

`PluginStatus` also exposes distribution name and version, package Summary,
Documentation URL and its extension, command and conformance factory
references when installed. Those values are inert provenance for a host
decision. A plugin has no specification URL, because each returned Extension
owns its own contract and descriptor.

The manager also reports an enabled plugin whose distribution has disappeared.
It remains visible as `installed=False` until disabled or installed again;
runtime composition fails instead of silently dropping a requested capability.

## Enable, disable and load

Activation is local host policy:

```python
manager.enable("example")

runtime = manager.runtime()
registry = runtime.registry
commands = manager.commands()

manager.disable("example")
```

An absent state file means that no plugin is enabled. The first change writes
the complete enabled set as versioned JSON. `OBST_CONFIG_HOME` overrides the
configuration directory; otherwise the manager uses the normal Windows
roaming or XDG configuration location. Corrupt state raises `PluginStateError`
and is never reset silently.

`enable()` and `disable()` update only that file. They do not import code.
Only a plugin with an Extension or command contribution can be enabled, because
a conformance-only plugin has no runtime contribution to activate. Trying to
enable one raises `PluginActivationError`; it remains available to explicit
`test()` calls.
`runtime()` imports Extension factories for the persistently enabled set plus
explicit one-shot additions, validates their tuple results and builds one
immutable registry for the caller's operation. It returns a `PluginRuntime`
containing the selected names and that registry. `commands()` separately loads
and captures commands from the persistently enabled set only. This separation
lets `--plugin NAME` add capabilities without executing a command factory whose
parser cannot appear in that invocation. Adapter code uses the registry's
captured contributions when it needs optional protocols; raw Extension
identities are not exposed as a second runtime view. There is no process-global
registry.

One-shot additions do not alter persistent state:

```python
runtime = manager.runtime(additional=("experiment",))
```

## Run published conformance cases

Testing is explicit and does not require the plugin to be enabled:

```python
report = manager.test("example")
assert report.passed
```

The manager loads the static suite and the target's Extension contribution
when one exists, validates those Extensions through an isolated registry, then
runs the portable cases through
[`obst.conformance`](../conformance.md#plugin-extension-suites).
The renderer-neutral report lists every case ID, kind, optional Extension ID,
pass state and failure text.

Dependencies remain explicit trust decisions. A suite may require another
installed capability, but the manager never discovers or enables its provider
automatically:

```python
report = manager.test("example", additional=("dependency",))
```

The target suite may test only Extension IDs contributed by the target plugin.
Complete-container cases may additionally name capabilities supplied by the
explicit dependency set.

Passing these cases proves only the published contracts covered by the cases.
It is not a sandbox, a package-signature check or a claim about unrelated code
inside the distribution.

## CLI workflow

The reference CLI uses the same manager:

```console
obst plugins list
obst plugins enable example
obst plugins disable example
obst plugins test example
obst plugins test example --plugin dependency
obst extensions
obst extensions --plugin experiment
```

The installed `obst-defaults` plugin is inactive until explicitly enabled.
Disabling it removes its contributed `pack` and `unpack` commands as well as its
Extension capabilities. Native `inspect` remains available and reports missing
capabilities from its otherwise empty or reduced registry. `--plugin NAME`
augments the runtime for a command whose parser is already available and does
not modify the enabled set. It cannot expose a command contributed only by that
inactive plugin, because command parsers are built from the persistently
enabled set. Enable a command-owning plugin before invoking its command. The
[CLI guide](../cli.md#manage-plugins-and-inspect-capabilities) owns the exact
commands and JSON projections.

## Conflicts and dependencies

Duplicate plugin contributions are rejected during discovery. Contributions
joined under one plugin name must come from the same physical distribution
record; equal self-declared project names and versions are not enough. Invalid
factories, imports, command contracts, callbacks and exit values raise
`PluginLoadError`. Duplicate command names across the enabled plugins, or a
command name reserved by the generic host, fail before command execution. One
Extension ID may be contributed by several
objects only when their kind and descriptor agree and each capability has one
provider at most. Conflicting identities or duplicate providers are rejected
when the manager composes the ordinary registry. Stage execution, parameter
codecs, metadata codecs and interpreters are independent capabilities under
that rule. File-specific source and materializer capabilities follow the same
per-ID rule when a file adapter composes the activated Extension objects.

The manager does not implement a second dependency graph. A Python distribution
declares installation dependencies through normal package metadata. Runtime
behavior depends on capabilities: if an operation needs `obst.file@1` and
`obst.zlib@1`, the activated set must supply the precise directional
capabilities the operation uses regardless of which plugin supplied them. The
manager does not silently enable another plugin because one plugin happens to
expect it. The same rule applies to conformance: additional providers are
named explicitly for that one test invocation and are not enabled persistently.

Plugins may contribute stages, stream profiles, carriers and packagers through
the same `obst.extensions` factory. The manager does not create separate entry
point groups for those capability kinds. CLI commands use `obst.commands`
because they compose capabilities for a host interface rather than enter the
registry. Archivers remain explicit application composition rather than
registry capabilities.

## Direct composition remains public

Applications and core tests with a fixed dependency set may bypass installed
package discovery entirely:

```python
from obst.core import ExtensionRegistry
from org_example_obst import TableExtension, WeirdCodecExtension

registry = ExtensionRegistry((TableExtension(), WeirdCodecExtension()))
```

That path and `PluginManager.runtime()` produce the same registry type and use
the same Extension validation. The manager adds installed-package policy; it
does not replace explicit dependency injection.
