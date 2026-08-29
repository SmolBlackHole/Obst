"""CLI composition contributed by the adaptive-zlib example plugin."""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
from typing import cast

from obst.cli import CliCommandError, CliContext
from obst.cli.commands import EXIT_PLUGIN, EXIT_SUCCESS
from obst.core import (
    BYTES_STREAM_TYPE,
    ChunkEncoder,
    ContainerWriter,
    ExtensionDeclaration,
    ExtensionRegistry,
    Manifest,
    MissingExtensionCapabilityError,
    MissingStageError,
    Recipe,
    StageParameterEncoder,
    StageSpec,
    Stream,
)

from obst_example_adaptive_zlib.extension import (
    AdaptiveZlibExtension,
    AdaptiveZlibParameters,
)
from obst_example_adaptive_zlib.output import (
    AdaptivePackResult,
    write_adaptive_pack_result,
)

_RAW_STAGE_ID = "obst.raw@1"
_CHUNK_SIZE = 64 * 1024


class AdaptivePackCommand:
    """Create one byte-stream container with adaptive-zlib and external RAW."""

    name = "adaptive-pack"
    summary = "pack one file with adaptive zlib through public plugin contracts"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("input", metavar="INPUT")
        parser.add_argument(
            "-o",
            "--output",
            required=True,
            metavar="OUTPUT",
            help="new OBST container to create",
        )
        parser.add_argument(
            "--level",
            type=int,
            choices=range(10),
            default=9,
            metavar="0..9",
            help="adaptive zlib compression level (default: 9)",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="emit a stable machine-readable package result",
        )

    def run(self, args: argparse.Namespace, context: CliContext) -> int:
        registry = context.registry
        self._require_stage_encoders(registry)
        parameter_encoder = registry.get_stage_parameter_encoder(
            AdaptiveZlibExtension.extension_id
        )
        if parameter_encoder is None:
            missing = MissingExtensionCapabilityError(
                AdaptiveZlibExtension.extension_id,
                capability="stage parameter encoder",
            )
            raise CliCommandError("plugin_error", EXIT_PLUGIN, missing)
        typed_parameter_encoder = cast(
            StageParameterEncoder[AdaptiveZlibParameters],
            parameter_encoder,
        )
        parameters = typed_parameter_encoder.encode_parameters(
            AdaptiveZlibParameters(compression_level=args.level)
        )
        recipe = Recipe(
            0,
            (
                StageSpec(AdaptiveZlibExtension.extension_id, parameters),
                StageSpec(_RAW_STAGE_ID),
            ),
        )
        manifest = Manifest(
            recipes=(recipe,),
            streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
            extensions=tuple(
                _declared_extension(registry, stage.stage_id) for stage in recipe.stages
            ),
        )
        logical = Path(args.input).read_bytes()
        target = BytesIO()
        writer = ContainerWriter(target, manifest, accounting=context.accounting)
        encoder = ChunkEncoder(registry, accounting=context.accounting)
        encoder.preflight((recipe,))
        for sequence, offset in enumerate(range(0, len(logical), _CHUNK_SIZE)):
            chunk = logical[offset : offset + _CHUNK_SIZE]
            writer.preflight_chunk(len(chunk))
            writer.write_chunk(
                encoder.encode(
                    chunk,
                    stream_id=0,
                    sequence=sequence,
                    recipe=recipe,
                )
            )
        result = writer.finish()
        container = target.getvalue()
        _write_new_file(Path(args.output), container)
        write_adaptive_pack_result(
            AdaptivePackResult(
                destination=Path(args.output),
                logical_size=len(logical),
                container_size=result.encoded_size,
                chunk_count=result.chunk_count,
            ),
            stdout=context.stdout,
            json_output=args.json,
        )
        return EXIT_SUCCESS

    @staticmethod
    def _require_stage_encoders(registry: ExtensionRegistry) -> None:
        for stage_id in (AdaptiveZlibExtension.extension_id, _RAW_STAGE_ID):
            try:
                registry.require_encoder_provider(stage_id)
            except MissingStageError as exc:
                raise CliCommandError("plugin_error", EXIT_PLUGIN, exc) from exc


def _declared_extension(
    registry: ExtensionRegistry,
    extension_id: str,
) -> ExtensionDeclaration:
    descriptor = registry.get_descriptor(extension_id)
    return ExtensionDeclaration(
        extension_id,
        None if descriptor is None else descriptor.specification_url,
    )


def _write_new_file(path: Path, data: bytes) -> None:
    target = path.open("xb")
    try:
        with target:
            offset = 0
            while offset < len(data):
                written = target.write(data[offset:])
                if written <= 0:
                    raise OSError("output file stopped accepting bytes")
                offset += written
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def obst_commands() -> tuple[AdaptivePackCommand, ...]:
    """Return this plugin's command contribution."""
    return (AdaptivePackCommand(),)


__all__ = ["AdaptivePackCommand", "obst_commands"]
