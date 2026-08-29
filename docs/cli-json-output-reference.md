# JSON CLI output reference

Parent: [OBST command-line guide](cli.md)

This non-normative snapshot collects every command in the repository that
accepts `--json`. It is meant for reviewing the machine interface in one place;
the command owner still defines each schema's meaning and compatibility.

The examples were captured with `obst-defaults` and `adaptive-zlib` enabled.
Temporary paths are normalized to `<TEMP>`. The resource section shows the
fields changed by each mutation and then one complete resolved resource array.
This avoids copying the same 17 resource records 4 times.

## Table of contents

- [JSON CLI output reference](#json-cli-output-reference)
	- [Table of contents](#table-of-contents)
	- [Plugin catalog](#plugin-catalog)
	- [Plugin conformance](#plugin-conformance)
	- [Extension inventory](#extension-inventory)
	- [Container inspection](#container-inspection)
	- [Resource limits](#resource-limits)
		- [Profile inventory](#profile-inventory)
		- [Profile mutations](#profile-mutations)
		- [Resolved profile](#resolved-profile)
	- [Contributed commands](#contributed-commands)

## Plugin catalog

```json
> obst plugins list --json
{
    "entry_point_groups": {
        "commands": "obst.commands",
        "conformance": "obst.conformance",
        "extensions": "obst.extensions",
        "resources": "obst.resources"
    },
    "plugins": [
        {
            "command_reference": "obst_example_adaptive_zlib:obst_commands",
            "conformance_reference": "obst_example_adaptive_zlib.conformance:obst_conformance",
            "distribution_name": "obst-example-adaptive-zlib",
            "distribution_version": "0.1.0",
            "documentation_url": "https://github.com/SmolBlackHole/Obst/blob/main/examples/plugin_adaptive_zlib/README.md",
            "enabled": true,
            "extension_reference": "obst_example_adaptive_zlib:obst_extensions",
            "installed": true,
            "name": "adaptive-zlib",
            "resource_reference": null,
            "summary": "Adaptive third-party zlib Stage plugin for OBST"
        },
        {
            "command_reference": "obst_defaults.commands:obst_commands",
            "conformance_reference": "obst_defaults.conformance:obst_conformance",
            "distribution_name": "obst-defaults",
            "distribution_version": "0.1.0",
            "documentation_url": "https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/README.md",
            "enabled": true,
            "extension_reference": "obst_defaults.bundle:obst_extensions",
            "installed": true,
            "name": "obst-defaults",
            "resource_reference": "obst_defaults.bundle:obst_resources",
            "summary": "Explicitly activated first-party tooling for OBST"
        },
        {
            "command_reference": null,
            "conformance_reference": "obst.format_conformance:obst_conformance",
            "distribution_name": "obst",
            "distribution_version": "0.1.0",
            "documentation_url": "https://github.com/SmolBlackHole/Obst/blob/main/docs/README.md",
            "enabled": false,
            "extension_reference": null,
            "installed": true,
            "name": "obst-format",
            "resource_reference": null,
            "summary": "Open binary container for chunked data and reversible pipelines"
        }
    ],
    "schema_version": 6
}
```

## Plugin conformance

The trust warning remains on stderr. Stdout contains only the JSON document:

```json
> obst plugins test adaptive-zlib --json
{
    "cases": [
        {
            "error": null,
            "extension_id": "org.example/adaptive-zlib@1",
            "id": "adaptive-known-answer",
            "kind": "stage-known-answer",
            "passed": true
        },
        {
            "error": null,
            "extension_id": "org.example/adaptive-zlib@1",
            "id": "adaptive-dictionary-known-answer",
            "kind": "stage-known-answer",
            "passed": true
        },
        {
            "error": null,
            "extension_id": "org.example/adaptive-zlib@1",
            "id": "adaptive-parameters",
            "kind": "stage-parameters",
            "passed": true
        },
        {
            "error": null,
            "extension_id": "org.example/adaptive-zlib@1",
            "id": "adaptive-parameters-rejected",
            "kind": "stage-bind-rejection",
            "passed": true
        },
        {
            "error": null,
            "extension_id": "org.example/adaptive-zlib@1",
            "id": "adaptive-payload-rejected",
            "kind": "stage-decode-rejection",
            "passed": true
        },
        {
            "error": null,
            "extension_id": "org.example/adaptive-zlib@1",
            "id": "adaptive-encode-limit",
            "kind": "stage-output-limit",
            "passed": true
        },
        {
            "error": null,
            "extension_id": "org.example/adaptive-zlib@1",
            "id": "adaptive-decode-limit",
            "kind": "stage-output-limit",
            "passed": true
        }
    ],
    "passed": true,
    "plugin": "adaptive-zlib",
    "schema_version": 2
}
```

## Extension inventory

```json
> obst extensions --json
{
    "extensions": [
        {
            "decoder_available": true,
            "display_name": "Delta8",
            "encoder_available": true,
            "id": "obst.delta8@1",
            "kind": "stage",
            "parameter_decoder_available": false,
            "parameter_encoder_available": false,
            "parameter_interpreter_available": false,
            "specification_url": "https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/delta8.md",
            "summary": "Modulo-256 delta transform over individual bytes."
        },
        {
            "display_name": "Portable file",
            "id": "obst.file@1",
            "kind": "stream_profile",
            "metadata_decoder_available": true,
            "metadata_encoder_available": true,
            "metadata_interpreter_available": true,
            "specification_url": "https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/streams/file.md",
            "summary": "One portable basename and its exact file bytes."
        },
        {
            "display_name": "Filesystem",
            "id": "obst.filesystem@1",
            "kind": "carrier",
            "publisher_available": true,
            "reader_available": true,
            "specification_url": "https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/carriers/filesystem.md",
            "summary": "Read or transactionally publish an OBST stream through a path.",
            "writer_available": false
        },
        {
            "display_name": "Fixed packager",
            "id": "obst.fixed@1",
            "kind": "packager",
            "provider_available": true,
            "specification_url": "https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/packagers/fixed.md",
            "summary": "Package each logical source once with its declared fixed recipe."
        },
        {
            "display_name": "Memory",
            "id": "obst.memory@1",
            "kind": "carrier",
            "publisher_available": true,
            "reader_available": true,
            "specification_url": "https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/carriers/memory.md",
            "summary": "Read or publish a complete OBST stream in memory.",
            "writer_available": false
        },
        {
            "display_name": "Standard input",
            "id": "obst.stdin@1",
            "kind": "carrier",
            "publisher_available": false,
            "reader_available": true,
            "specification_url": "https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/carriers/standard-input.md",
            "summary": "Read an OBST stream from a host-owned standard-input endpoint.",
            "writer_available": false
        },
        {
            "decoder_available": true,
            "display_name": "zlib",
            "encoder_available": true,
            "id": "obst.zlib@1",
            "kind": "stage",
            "parameter_decoder_available": true,
            "parameter_encoder_available": true,
            "parameter_interpreter_available": true,
            "specification_url": "https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/zlib.md",
            "summary": "zlib-wrapped DEFLATE with a declared compression level."
        },
        {
            "decoder_available": true,
            "display_name": "zlib with preset dictionary",
            "encoder_available": true,
            "id": "obst.zlib@2",
            "kind": "stage",
            "parameter_decoder_available": true,
            "parameter_encoder_available": true,
            "parameter_interpreter_available": true,
            "specification_url": "https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/zlib-dictionary.md",
            "summary": "zlib-wrapped DEFLATE with a self-described preset dictionary."
        },
        {
            "decoder_available": true,
            "display_name": "Adaptive zlib",
            "encoder_available": true,
            "id": "org.example/adaptive-zlib@1",
            "kind": "stage",
            "parameter_decoder_available": true,
            "parameter_encoder_available": true,
            "parameter_interpreter_available": true,
            "specification_url": "https://github.com/SmolBlackHole/Obst/blob/main/examples/plugin_adaptive_zlib/README.md#stage-contract",
            "summary": "Chooses one byte-lane layout and optional preset dictionary for each chunk before zlib compression."
        }
    ],
    "schema_version": 3
}
```

## Container inspection

```json
> obst inspect <TEMP>\readme.obst --json
{
    "chunks": 1,
    "container_size": 8239,
    "container_to_original_ratio": 0.42294661190965094,
    "encoded_payload_size": 7794,
    "format": {
        "codename": "apple",
        "label": "0.1-apple",
        "major": 0,
        "minor": 1,
        "name": "OBST"
    },
    "integrity": "valid",
    "interpretation_policy": {
        "extension_ids": [
            "obst.file@1",
            "obst.zlib@1",
            "obst.zlib@2",
            "org.example/adaptive-zlib@1"
        ]
    },
    "logical_recovery": "not_attempted",
    "missing_declared_stages": [],
    "missing_required_stages": [],
    "original_size": 19480,
    "recipe_details": [
        {
            "chunks": 1,
            "id": 0,
            "stages": [
                {
                    "id": "obst.zlib@1",
                    "parameters_hex": "09",
                    "parameters_interpretation": {
                        "error": null,
                        "fields": {
                            "compression_level": 9
                        },
                        "label": null
                    }
                }
            ]
        }
    ],
    "recipes": 1,
    "required_decoders_available": true,
    "resource_footprint": {
        "chunk_count": 1,
        "container_size": 8239,
        "extension_count": 2,
        "logical_size": 19480,
        "manifest_size": 285,
        "max_encoded_chunk_size": 7794,
        "max_logical_chunk_size": 19480,
        "max_materialized_stream_size": 19480,
        "max_stages_per_recipe": 1,
        "recipe_count": 1,
        "stage_executions": 1,
        "stream_count": 1,
        "total_stage_count": 1
    },
    "schema_version": 6,
    "stage_details": [
        {
            "declared_recipe_ids": [
                0
            ],
            "declared_specification_url": "https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/zlib.md",
            "decoder_available": true,
            "display_name": "zlib",
            "id": "obst.zlib@1",
            "local_specification_url": "https://github.com/SmolBlackHole/Obst/blob/main/plugins/defaults/docs/contracts/stages/zlib.md",
            "required": true,
            "summary": "zlib-wrapped DEFLATE with a declared compression level.",
            "used_chunks_by_recipe": [
                {
                    "chunks": 1,
                    "recipe_id": 0
                }
            ],
            "used_recipe_ids": [
                0
            ]
        }
    ],
    "stream_details": [
        {
            "chunks": 1,
            "default_recipe": 0,
            "encoded_payload_size": 7794,
            "id": 0,
            "metadata_hex": "524541444d452e6d64",
            "metadata_interpretation": {
                "error": null,
                "fields": {
                    "name": "README.md"
                },
                "label": "README.md"
            },
            "original_size": 19480,
            "recipe_usage": [
                {
                    "chunks": 1,
                    "recipe_id": 0
                }
            ],
            "type": "obst.file@1"
        }
    ],
    "streams": 1
}
```

## Resource limits

### Profile inventory

```json
> obst limits profiles --json
{
    "profiles": [
        {
            "active": true,
            "available": true,
            "id": "default",
            "mutable": false,
            "source": "default",
            "summary": "Built-in resource ceilings contributed by the active runtime."
        }
    ],
    "schema_version": 1
}
```

### Profile mutations

`create` returns the same complete `resources` array with a new mutable profile:

```json
> obst limits create local --json
{
    "profile": {
        "active": false,
        "available": true,
        "id": "local",
        "mutable": true,
        "source": "custom",
        "summary": "Local custom resource profile."
    },
    "resources": "same complete resource array as `obst limits show --json`",
    "schema_version": 1
}
```

The string in place of `resources` above is an editorial abbreviation in this
snapshot, not literal command output. The real command returns the complete
array. `set` changes the selected resource's exact maximum and source:

```json
> obst limits set local manifest_bytes 8388608 --json
{
    "profile": {
        "active": false,
        "available": true,
        "id": "local",
        "mutable": true,
        "source": "custom",
        "summary": "Local custom resource profile."
    },
    "resources": [
        {
            "available": true,
            "default_maximum": 16777216,
            "id": "manifest_bytes",
            "owner": "core",
            "profile_source": "local",
            "resolved_maximum": 8388608,
            "summary": "Bytes in one encoded manifest."
        }
    ],
    "schema_version": 1
}
```

That one-element array is also an editorial abbreviation; the command retains
all unchanged resource records. `use` changes `profile.active` to `true` and
again returns the complete resolved array:

```json
> obst limits use local --json
{
    "profile": {
        "active": true,
        "available": true,
        "id": "local",
        "mutable": true,
        "source": "custom",
        "summary": "Local custom resource profile."
    },
    "resources": "complete resource array with the local override",
    "schema_version": 1
}
```

After `obst limits use default --json` returns the complete default profile
shown above, deletion has a compact independent result:

```json
> obst limits delete local --json
{
    "deleted_profile": "local",
    "schema_version": 1
}
```

### Resolved profile

`show`, `create`, `set` and `use` all return this schema. Byte values remain
exact integers rather than human-readable KiB, MiB or GiB strings.

```json
> obst limits show --json
{
    "profile": {
        "active": true,
        "available": true,
        "id": "default",
        "mutable": false,
        "source": "default",
        "summary": "Built-in resource ceilings contributed by the active runtime."
    },
    "resources": [
        {
            "available": true,
            "default_maximum": 262144,
            "id": "chunks",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 262144,
            "summary": "Chunks in one container."
        },
        {
            "available": true,
            "default_maximum": 17179869184,
            "id": "container_bytes",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 17179869184,
            "summary": "Bytes in one complete container."
        },
        {
            "available": true,
            "default_maximum": 67108864,
            "id": "encoded_chunk_bytes",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 67108864,
            "summary": "Encoded bytes in one chunk."
        },
        {
            "available": true,
            "default_maximum": 4096,
            "id": "extensions",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 4096,
            "summary": "Extension declarations in one manifest."
        },
        {
            "available": true,
            "default_maximum": 67108864,
            "id": "intermediate_bytes",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 67108864,
            "summary": "Bytes in one pipeline intermediate."
        },
        {
            "available": true,
            "default_maximum": 17179869184,
            "id": "logical_bytes",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 17179869184,
            "summary": "Logical bytes processed by one operation."
        },
        {
            "available": true,
            "default_maximum": 67108864,
            "id": "logical_chunk_bytes",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 67108864,
            "summary": "Logical bytes in one chunk."
        },
        {
            "available": true,
            "default_maximum": 16777216,
            "id": "manifest_bytes",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 16777216,
            "summary": "Bytes in one encoded manifest."
        },
        {
            "available": true,
            "default_maximum": 67108864,
            "id": "materialized_stream_bytes",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 67108864,
            "summary": "Bytes in one materialized stream."
        },
        {
            "available": true,
            "default_maximum": 4294967296,
            "id": "obst.file@1/archive_member_bytes",
            "owner": "obst.file@1",
            "profile_source": "default",
            "resolved_maximum": 4294967296,
            "summary": "Logical bytes restored for one file."
        },
        {
            "available": true,
            "default_maximum": 4096,
            "id": "obst.file@1/archive_members",
            "owner": "obst.file@1",
            "profile_source": "default",
            "resolved_maximum": 4096,
            "summary": "Files restored by one extraction operation."
        },
        {
            "available": true,
            "default_maximum": 17179869184,
            "id": "obst.file@1/archive_total_bytes",
            "owner": "obst.file@1",
            "profile_source": "default",
            "resolved_maximum": 17179869184,
            "summary": "Logical file bytes restored by one extraction operation."
        },
        {
            "available": true,
            "default_maximum": 4096,
            "id": "recipes",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 4096,
            "summary": "Recipes in one manifest."
        },
        {
            "available": true,
            "default_maximum": 1048576,
            "id": "stage_executions",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 1048576,
            "summary": "Stage executions in one operation."
        },
        {
            "available": true,
            "default_maximum": 64,
            "id": "stages_per_recipe",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 64,
            "summary": "Stages in one recipe."
        },
        {
            "available": true,
            "default_maximum": 65536,
            "id": "streams",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 65536,
            "summary": "Streams in one manifest."
        },
        {
            "available": true,
            "default_maximum": 65536,
            "id": "total_stages",
            "owner": "core",
            "profile_source": "default",
            "resolved_maximum": 65536,
            "summary": "Stages across all recipes in one manifest."
        }
    ],
    "schema_version": 1
}
```

## Contributed commands

`obst-defaults` owns the first 2 schemas. Cleanup warnings remain on stderr;
the JSON documents also retain their structured cleanup facts.

```json
> obst pack README.md -o <TEMP>\readme-json.obst --json
{
    "cleanup_issues": [],
    "container_size": 8239,
    "destination": "<TEMP>\\readme-json.obst",
    "files": [
        {
            "chunks": 1,
            "logical_size": 19480,
            "name": "README.md"
        }
    ],
    "schema_version": 1
}
```

```json
> obst unpack <TEMP>\readme-json.obst -o <TEMP>\restored-json --json
{
    "cleanup_issues": [],
    "destination": "<TEMP>\\restored-json",
    "files": [
        {
            "name": "README.md",
            "path": "<TEMP>\\restored-json\\README.md"
        }
    ],
    "schema_version": 1,
    "windows_origin_not_propagated": false
}
```

The example plugin owns the adaptive result schema:

```json
> obst adaptive-pack README.md -o <TEMP>\readme-adaptive-json.obst --json
{
    "chunks": 1,
    "container_size": 8279,
    "destination": "<TEMP>\\readme-adaptive-json.obst",
    "logical_size": 19480,
    "schema_version": 1
}
```
