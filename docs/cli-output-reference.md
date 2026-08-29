# Human-readable CLI output reference

Parent: [OBST command-line guide](cli.md)

This page is a non-normative snapshot of every human-readable command exposed
by the runtime and the installed example plugins used in this repository. It
exists to review the CLI as one interface. Command behavior remains owned by
the [CLI guide](cli.md) and by each contributing plugin's documentation.

The examples were captured with `obst-defaults` and `adaptive-zlib` installed.
Both plugins are enabled where their contributions are needed. ANSI colors are
omitted because the output was captured rather than written to a terminal, and
temporary paths are normalized to `<TEMP>`. JSON variants live in the separate
[JSON output reference](cli-json-output-reference.md).

## Table of contents

- [Human-readable CLI output reference](#human-readable-cli-output-reference)
	- [Table of contents](#table-of-contents)
	- [Invocation and help](#invocation-and-help)
	- [Plugin management](#plugin-management)
	- [Extension inventory](#extension-inventory)
	- [Container inspection](#container-inspection)
	- [Resource limits](#resource-limits)
		- [Change limits](#change-limits)
		- [List and show profiles](#list-and-show-profiles)
		- [Create a profile](#create-a-profile)
		- [Set a ceiling](#set-a-ceiling)
		- [Select and delete a profile](#select-and-delete-a-profile)
	- [Contributed commands](#contributed-commands)

## Invocation and help

With both example plugins enabled, invoking `obst` without a command shows the
available command set and exits with an argument error:

```console
> obst
usage: obst [-h] [--version]
            {plugins,extensions,inspect,limits,adaptive-pack,pack,unpack,help} ...
obst: error: the following arguments are required: command
```

```console
> obst --version
obst format 0.1-apple
```

```console
> obst help
usage: obst [-h] [--version]
            {plugins,extensions,inspect,limits,adaptive-pack,pack,unpack,help} ...

positional arguments:
  {plugins,extensions,inspect,limits,adaptive-pack,pack,unpack,help}
    plugins             inspect and manage installed plugins
    extensions          show capabilities provided by enabled and one-shot
                        plugins
    inspect             validate and describe a container without decoding
                        payloads
    limits              inspect and manage local resource limit profiles
    adaptive-pack       pack one file with adaptive zlib through public plugin
                        contracts
    pack                pack explicit regular files into one OBST archive
    unpack              extract every file stream without overwriting existing
                        files
    help                show general help or help for a command

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit

Run 'obst help COMMAND' for command-specific help.
```

`help` also accepts a command name. For example:

```console
> obst help limits
usage: obst limits [-h] {profiles,show,create,set,use,delete} ...

positional arguments:
  {profiles,show,create,set,use,delete}
    profiles            list built-in, contributed and custom profiles
    show                show resolved resource ceilings for one profile
    create              create one empty custom profile
    set                 set one resource override on a custom profile
    use                 persistently select one available profile
    delete              delete one inactive custom profile

options:
  -h, --help            show this help message and exit
```

## Plugin management

Discovery reads package metadata without loading plugin code:

```console
> obst plugins list
Extension plugins
  Metadata only; plugin code was not loaded.

adaptive-zlib
  Installed       yes
  Enabled         yes
  Distribution    obst-example-adaptive-zlib 0.1.0
  Summary         Adaptive third-party zlib Stage plugin for OBST
  Documentation   https://github.com/SmolBlackHole/Obst/blob/main/examples/plugin_adaptive_zlib/README.md
  Extensions      obst_example_adaptive_zlib:obst_extensions
  Commands        obst_example_adaptive_zlib:obst_commands
  Conformance     obst_example_adaptive_zlib.conformance:obst_conformance

obst-defaults
  Installed       yes
  Enabled         yes
  Distribution    obst-defaults 0.1.0
  Summary         Explicitly activated first-party tooling for OBST
  Documentation   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/README.md
  Extensions      obst_defaults.bundle:obst_extensions
  Commands        obst_defaults.commands:obst_commands
  Conformance     obst_defaults.conformance:obst_conformance
  Resources       obst_defaults.bundle:obst_resources

obst-format
  Installed       yes
  Enabled         no
  Distribution    obst 0.1.0
  Summary         Open binary container for chunked data and reversible pipelines
  Documentation   https://github.com/SmolBlackHole/Obst/blob/main/docs/README.md
  Conformance     obst.format_conformance:obst_conformance
```

Activation commands modify only the local plugin selection:

```console
> obst plugins enable obst-defaults
Enabled plugin obst-defaults

> obst plugins disable obst-defaults
Disabled plugin obst-defaults
```

Conformance testing loads and executes the selected plugin's published test
code. It is not a sandbox:

```console
> obst plugins test adaptive-zlib
obst: warning: plugin conformance executes installed plugin code with your current process privileges. No sandbox is used. Test only plugins you trust.
Plugin conformance
  Plugin          adaptive-zlib
  Result          passed

Cases
  Case                              Result  Kind                    Extension
  --------------------------------  ------  ----------------------  ---------------------------
  adaptive-known-answer             PASS    stage-known-answer      org.example/adaptive-zlib@1
  adaptive-dictionary-known-answer  PASS    stage-known-answer      org.example/adaptive-zlib@1
  adaptive-parameters               PASS    stage-parameters        org.example/adaptive-zlib@1
  adaptive-parameters-rejected      PASS    stage-bind-rejection    org.example/adaptive-zlib@1
  adaptive-payload-rejected         PASS    stage-decode-rejection  org.example/adaptive-zlib@1
  adaptive-encode-limit             PASS    stage-output-limit      org.example/adaptive-zlib@1
  adaptive-decode-limit             PASS    stage-output-limit      org.example/adaptive-zlib@1
```

## Extension inventory

```console
> obst extensions
Extension capabilities

Stages

obst.delta8@1
  Name            Delta8
  Stage           encode yes, decode yes
  Parameters      encode no, decode no, interpret no
  Summary         Modulo-256 delta transform over individual bytes.
  Specification   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/delta8.md

obst.raw@1
  Name            RAW
  Stage           encode yes, decode yes
  Parameters      encode no, decode no, interpret no
  Summary         Identity stage for untransformed bytes.
  Specification   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/raw.md

obst.zlib@1
  Name            zlib
  Stage           encode yes, decode yes
  Parameters      encode yes, decode yes, interpret yes
  Summary         zlib-wrapped DEFLATE with a declared compression level.
  Specification   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/zlib.md

obst.zlib@2
  Name            zlib with preset dictionary
  Stage           encode yes, decode yes
  Parameters      encode yes, decode yes, interpret yes
  Summary         zlib-wrapped DEFLATE with a self-described preset dictionary.
  Specification   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/zlib-dictionary.md

org.example/adaptive-zlib@1
  Name            Adaptive zlib
  Stage           encode yes, decode yes
  Parameters      encode yes, decode yes, interpret yes
  Summary         Chooses one byte-lane layout and optional preset dictionary for each chunk before zlib compression.
  Specification   https://github.com/SmolBlackHole/Obst/blob/main/examples/plugin_adaptive_zlib/README.md#stage-contract

Stream profiles

obst.file@1
  Name            Portable file
  Kind            stream profile
  Metadata        encode yes, decode yes, interpret yes
  Summary         One portable basename and its exact file bytes.
  Specification   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/streams/file.md

Carriers

obst.filesystem@1
  Name            Filesystem
  Carrier         read yes, write no, publish yes
  Summary         Read or transactionally publish an OBST stream through a path.
  Specification   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/carriers/filesystem.md

obst.memory@1
  Name            Memory
  Carrier         read yes, write no, publish yes
  Summary         Read or publish a complete OBST stream in memory.
  Specification   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/carriers/memory.md

obst.stdin@1
  Name            Standard input
  Carrier         read yes, write no, publish no
  Summary         Read an OBST stream from a host-owned standard-input endpoint.
  Specification   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/carriers/standard-input.md

Packagers

obst.fixed@1
  Name            Fixed packager
  Packager        prepare yes
  Summary         Package each logical source once with its declared fixed recipe.
  Specification   https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/packagers/fixed.md
```

## Container inspection

The example container below was created from the repository `README.md` by the
`pack` command shown later on this page:

```console
> obst inspect <TEMP>\readme.obst
                     ███████
                   ██    ██
             ██   █  █████
               █ █ ████

         █████████████████        OBST container 0.1-apple
       █████████████████████      -------------------------
                                  Streams                       1
     ████████████████████████     Recipes                       1
     ████████████████████████     Chunks                        1
                                  Container size                8.0 KiB
     ████████████████████████     Original size                 19.0 KiB (committed)
      ███████████████████████     Compression                   57.7% smaller (42.3% of original)
                                  Integrity                     valid (terminal commit and encoded CRCs)
        ███████████████████       Required decoders available   yes
          ██████████████          Logical recovery              not attempted

Streams
  [0] README.md
      obst.file@1 | 1 chunk | original 19.0 KiB | encoded payload 7.6 KiB
      Recipe usage: yes (1 total; recipe 0: 1)

Recipes
  [0] obst.zlib@1(compression_level=9) | 1 chunk

Resource footprint
  Manifest 285 B | largest chunk 19.0 KiB logical / 7.6 KiB encoded
  Stage executions 1 | largest stream 19.0 KiB if materialized

Stage capabilities
  obst.zlib@1 (zlib): decoder available
      Declared by recipe: 0
      Used by chunks: yes (1 total; recipe 0: 1)
      zlib-wrapped DEFLATE with a declared compression level.
      Declared specification: https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/zlib.md
      Local specification: https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/zlib.md
```

## Resource limits

### Change limits

Limits are changed by creating a mutable local profile, writing overrides into
it and selecting it. Built-in and plugin-contributed profiles are immutable.
There is no independent enable or disable state for profiles: exactly one
available profile is active.

```console
> obst limits create local
> obst limits set local manifest_bytes 8388608
> obst limits use local
```

Plugin-owned resources use the same command with their complete namespaced
resource ID, for example:

```console
> obst limits set local obst.file@1/archive_members 128
```

`MAXIMUM` is a non-negative integer in the resource's base unit. Use `none` to
remove one ceiling from the custom profile:

```console
> obst limits set local chunks none
```

Return to the immutable default before deleting an active custom profile:

```console
> obst limits use default
> obst limits delete local
```

### List and show profiles

```console
> obst limits profiles
Resource limit profiles

  Profile  Source   Active  Available  Mutable
  -------  -------  ------  ---------  -------
  default  default  yes     yes        no
```

```console
> obst limits show
Resource limit profile
  Profile         default
  Source          default
  Active          yes
  Available       yes
  Summary         Built-in resource ceilings contributed by the active runtime.

Resources

Core
  Resource                     Default    Maximum
  -------------------------  ---------  ---------
  chunks                       262,144    262,144
  container_bytes             16.0 GiB   16.0 GiB
  encoded_chunk_bytes         64.0 MiB   64.0 MiB
  extensions                     4,096      4,096
  intermediate_bytes          64.0 MiB   64.0 MiB
  logical_bytes               16.0 GiB   16.0 GiB
  logical_chunk_bytes         64.0 MiB   64.0 MiB
  manifest_bytes              16.0 MiB   16.0 MiB
  materialized_stream_bytes   64.0 MiB   64.0 MiB
  recipes                        4,096      4,096
  stage_executions           1,048,576  1,048,576
  stages_per_recipe                 64         64
  streams                       65,536     65,536
  total_stages                  65,536     65,536

obst.file@1
  Resource               Default   Maximum
  --------------------  --------  --------
  archive_member_bytes   4.0 GiB   4.0 GiB
  archive_members          4,096     4,096
  archive_total_bytes   16.0 GiB  16.0 GiB
```

### Create a profile

`create` prints the complete resolved profile. A new profile initially
inherits every available default:

```console
> obst limits create local
Resource limit profile
  Profile         local
  Source          custom
  Active          no
  Available       yes
  Summary         Local custom resource profile.

Resources

Core
  Resource                     Default    Maximum  Source
  -------------------------  ---------  ---------  -------
  chunks                       262,144    262,144  default
  container_bytes             16.0 GiB   16.0 GiB  default
  encoded_chunk_bytes         64.0 MiB   64.0 MiB  default
  extensions                     4,096      4,096  default
  intermediate_bytes          64.0 MiB   64.0 MiB  default
  logical_bytes               16.0 GiB   16.0 GiB  default
  logical_chunk_bytes         64.0 MiB   64.0 MiB  default
  manifest_bytes              16.0 MiB   16.0 MiB  default
  materialized_stream_bytes   64.0 MiB   64.0 MiB  default
  recipes                        4,096      4,096  default
  stage_executions           1,048,576  1,048,576  default
  stages_per_recipe                 64         64  default
  streams                       65,536     65,536  default
  total_stages                  65,536     65,536  default

obst.file@1
  Resource               Default   Maximum  Source
  --------------------  --------  --------  -------
  archive_member_bytes   4.0 GiB   4.0 GiB  default
  archive_members          4,096     4,096  default
  archive_total_bytes   16.0 GiB  16.0 GiB  default
```

### Set a ceiling

`set` prints the profile after applying the override. Here the manifest ceiling
changes from `16.0 MiB` to `8.0 MiB`:

```console
> obst limits set local manifest_bytes 8388608
Resource limit profile
  Profile         local
  Source          custom
  Active          no
  Available       yes
  Summary         Local custom resource profile.

Resources

Core
  Resource                     Default    Maximum  Source
  -------------------------  ---------  ---------  -------
  chunks                       262,144    262,144  default
  container_bytes             16.0 GiB   16.0 GiB  default
  encoded_chunk_bytes         64.0 MiB   64.0 MiB  default
  extensions                     4,096      4,096  default
  intermediate_bytes          64.0 MiB   64.0 MiB  default
  logical_bytes               16.0 GiB   16.0 GiB  default
  logical_chunk_bytes         64.0 MiB   64.0 MiB  default
  manifest_bytes              16.0 MiB    8.0 MiB  local
  materialized_stream_bytes   64.0 MiB   64.0 MiB  default
  recipes                        4,096      4,096  default
  stage_executions           1,048,576  1,048,576  default
  stages_per_recipe                 64         64  default
  streams                       65,536     65,536  default
  total_stages                  65,536     65,536  default

obst.file@1
  Resource               Default   Maximum  Source
  --------------------  --------  --------  -------
  archive_member_bytes   4.0 GiB   4.0 GiB  default
  archive_members          4,096     4,096  default
  archive_total_bytes   16.0 GiB  16.0 GiB  default
```

Extension-owned resources use their complete namespaced ID. Applying
`obst.file@1/archive_members 128` changes that row to:

```text
  archive_members          4,096       128  local
```

### Select and delete a profile

`use` prints the selected resolved profile:

```console
> obst limits use local
Resource limit profile
  Profile         local
  Source          custom
  Active          yes
  Available       yes
  Summary         Local custom resource profile.

Resources

Core
  Resource                     Default    Maximum  Source
  -------------------------  ---------  ---------  -------
  chunks                       262,144    262,144  default
  container_bytes             16.0 GiB   16.0 GiB  default
  encoded_chunk_bytes         64.0 MiB   64.0 MiB  default
  extensions                     4,096      4,096  default
  intermediate_bytes          64.0 MiB   64.0 MiB  default
  logical_bytes               16.0 GiB   16.0 GiB  default
  logical_chunk_bytes         64.0 MiB   64.0 MiB  default
  manifest_bytes              16.0 MiB    8.0 MiB  local
  materialized_stream_bytes   64.0 MiB   64.0 MiB  default
  recipes                        4,096      4,096  default
  stage_executions           1,048,576  1,048,576  default
  stages_per_recipe                 64         64  default
  streams                       65,536     65,536  default
  total_stages                  65,536     65,536  default

obst.file@1
  Resource               Default   Maximum  Source
  --------------------  --------  --------  -------
  archive_member_bytes   4.0 GiB   4.0 GiB  default
  archive_members          4,096     4,096  default
  archive_total_bytes   16.0 GiB  16.0 GiB  default
```

After returning to `default`, the inactive custom profile can be deleted:

```console
> obst limits use default
Resource limit profile
  Profile         default
  Source          default
  Active          yes
  Available       yes
  Summary         Built-in resource ceilings contributed by the active runtime.

Resources

Core
  Resource                     Default    Maximum
  -------------------------  ---------  ---------
  chunks                       262,144    262,144
  container_bytes             16.0 GiB   16.0 GiB
  encoded_chunk_bytes         64.0 MiB   64.0 MiB
  extensions                     4,096      4,096
  intermediate_bytes          64.0 MiB   64.0 MiB
  logical_bytes               16.0 GiB   16.0 GiB
  logical_chunk_bytes         64.0 MiB   64.0 MiB
  manifest_bytes              16.0 MiB   16.0 MiB
  materialized_stream_bytes   64.0 MiB   64.0 MiB
  recipes                        4,096      4,096
  stage_executions           1,048,576  1,048,576
  stages_per_recipe                 64         64
  streams                       65,536     65,536
  total_stages                  65,536     65,536

obst.file@1
  Resource               Default   Maximum
  --------------------  --------  --------
  archive_member_bytes   4.0 GiB   4.0 GiB
  archive_members          4,096     4,096
  archive_total_bytes   16.0 GiB  16.0 GiB

> obst limits delete local
Deleted limit profile local
```

## Contributed commands

`obst-defaults` contributes `pack` and `unpack` through the same command entry
point available to third-party plugins:

```console
> obst pack README.md -o <TEMP>\readme.obst
Packed 1 file
  Destination     <TEMP>\readme.obst
  Container size  8.0 KiB

Files
  File           Size  Chunks
  ---------  --------  ------
  README.md  19.0 KiB       1
```

```console
> obst unpack <TEMP>\readme.obst -o <TEMP>\restored
Unpacked 1 file
  Destination     <TEMP>\restored

Files
  File
  ---------
  README.md
```

The installable `adaptive-zlib` example contributes its own command:

```console
> obst adaptive-pack README.md -o <TEMP>\readme-adaptive.obst
Adaptive pack complete
  Logical size    19.0 KiB
  Container size  8.1 KiB
  Chunks          1
```
