"""First-party CLI commands contributed through the ordinary plugin path."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

from obst.cli import CliCommandError, CliContext
from obst.cli.commands import EXIT_SUCCESS
from obst.core.container import ContainerReader
from obst.core.extensions import (
    CarrierPublisherProvider,
    CarrierReaderProvider,
    PackagerProvider,
    StageParameterEncoder,
)
from obst.core.model import StageSpec
from obst.core.packaging import RecipeSpec
from obst.core.registry import ExtensionRegistry
from obst.plugins import PluginLoadError
from obst_defaults.carriers import (
    CarrierError,
    PublicationReceipt,
    publish_package,
)
from obst_defaults.carriers.filesystem import (
    FilesystemPublishRequest,
    FilesystemReadRequest,
)
from obst_defaults.cleanup import close_all
from obst_defaults.codecs.zlib import ZlibParameters
from obst_defaults.files import FileArchiveError, FileArchiver, FileProfileError
from obst_defaults.output import (
    PackCommandMember,
    PackCommandResult,
    write_pack_result,
    write_unpack_result,
)
from obst_defaults.packagers.fixed import FixedPackageRequest

FILE_PROFILE_ID = "obst.file@1"
ZLIB_STAGE_ID = "obst.zlib@1"
FILESYSTEM_CARRIER_ID = "obst.filesystem@1"
FIXED_PACKAGER_ID = "obst.fixed@1"
EXIT_ARCHIVE = 7
EXIT_CARRIER = 8
EXIT_PROFILE = 9


class PackCommand:
    """Pack explicit regular files with the first-party fixed policy."""

    name = "pack"
    summary = "pack explicit regular files into one OBST archive"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.description = (
            "Create OUTPUT from one or more positional INPUT files. Name the "
            "destination explicitly with -o/--output; existing outputs are "
            "never overwritten."
        )
        parser.epilog = (
            "example:\n  obst pack apple.jpg banana.jpg -o samples/fruits.obst"
        )
        parser.formatter_class = argparse.RawDescriptionHelpFormatter
        parser.add_argument(
            "inputs",
            nargs="+",
            metavar="INPUT",
            help="one or more existing regular files to store",
        )
        parser.add_argument(
            "-o",
            "--output",
            required=True,
            metavar="OUTPUT",
            help="new .obst container to create",
        )

    def run(self, args: argparse.Namespace, context: CliContext) -> int:
        try:
            return _pack_paths(
                context,
                output_path=args.output,
                input_paths=args.inputs,
            )
        except FileProfileError as exc:
            raise CliCommandError("profile_error", EXIT_PROFILE, exc) from exc
        except FileArchiveError as exc:
            raise CliCommandError("archive_error", EXIT_ARCHIVE, exc) from exc
        except CarrierError as exc:
            raise CliCommandError("carrier_error", EXIT_CARRIER, exc) from exc


class UnpackCommand:
    """Restore every supported portable file stream."""

    name = "unpack"
    summary = "extract every file stream without overwriting existing files"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.description = (
            "Extract every file stream from INPUT into OUTPUT_DIRECTORY. Name "
            "the destination explicitly with -o/--output; existing files are "
            "never overwritten."
        )
        parser.epilog = "example:\n  obst unpack fruits.obst -o restored"
        parser.formatter_class = argparse.RawDescriptionHelpFormatter
        parser.add_argument(
            "input",
            metavar="INPUT",
            help=".obst file archive to extract",
        )
        parser.add_argument(
            "-o",
            "--output",
            required=True,
            metavar="OUTPUT_DIRECTORY",
            help=(
                "new or existing directory; existing member targets are never "
                "overwritten"
            ),
        )

    def run(self, args: argparse.Namespace, context: CliContext) -> int:
        try:
            return _unpack_path(
                context,
                input_path=args.input,
                output_directory=args.output,
            )
        except FileProfileError as exc:
            raise CliCommandError("profile_error", EXIT_PROFILE, exc) from exc
        except FileArchiveError as exc:
            raise CliCommandError("archive_error", EXIT_ARCHIVE, exc) from exc
        except CarrierError as exc:
            raise CliCommandError("carrier_error", EXIT_CARRIER, exc) from exc


def obst_commands() -> tuple[PackCommand, UnpackCommand]:
    """Return the first-party commands without registering them globally."""
    return (PackCommand(), UnpackCommand())


def _file_archiver(registry: ExtensionRegistry) -> FileArchiver:
    return FileArchiver(registry)


def _default_file_recipe(
    registry: ExtensionRegistry,
    plugin_names: tuple[str, ...],
) -> RecipeSpec:
    parameter_encoder = registry.get_stage_parameter_encoder(ZLIB_STAGE_ID)
    if parameter_encoder is None:
        selected = ", ".join(plugin_names) or "<none>"
        raise PluginLoadError(
            selected,
            f"runtime must provide exactly one parameter encoder for {ZLIB_STAGE_ID}",
        )
    typed_encoder = cast(StageParameterEncoder[ZlibParameters], parameter_encoder)
    try:
        parameters = typed_encoder.encode_parameters(ZlibParameters(9))
    except Exception as exc:
        selected = ", ".join(plugin_names) or "<none>"
        raise PluginLoadError(
            selected,
            f"{ZLIB_STAGE_ID} parameter encoder raised {type(exc).__name__}: {exc}",
        ) from exc
    if type(parameters) is not bytes:
        selected = ", ".join(plugin_names) or "<none>"
        raise PluginLoadError(
            selected,
            f"{ZLIB_STAGE_ID} parameter encoder must return exact bytes",
        )
    return RecipeSpec((StageSpec(ZLIB_STAGE_ID, parameters),))


def _pack_paths(
    context: CliContext,
    *,
    output_path: str,
    input_paths: list[str],
) -> int:
    registry = context.registry
    packager = cast(
        PackagerProvider[FixedPackageRequest],
        registry.require_packager_provider(FIXED_PACKAGER_ID),
    )
    publisher = cast(
        CarrierPublisherProvider[
            FilesystemPublishRequest,
            PublicationReceipt[Path],
        ],
        registry.require_carrier_publisher_provider(FILESYSTEM_CARRIER_ID),
    )
    file_archiver = _file_archiver(registry)
    recipe = _default_file_recipe(registry, context.plugin_names)
    target = Path(output_path)
    source_paths = tuple(Path(input_path) for input_path in input_paths)
    resolved_target = target.resolve()
    if any(source_path.resolve() == resolved_target for source_path in source_paths):
        raise FileArchiveError("output path cannot also be an input file")
    with file_archiver.open_sources(
        source_paths,
        source_profile_id=FILE_PROFILE_ID,
        recipe=recipe,
    ) as sources:
        member_names = tuple(
            file_archiver.plan_file(
                source.descriptor.stream_type,
                source.descriptor.metadata,
            ).name
            for source in sources
        )
        operation = packager.prepare_package(FixedPackageRequest(registry, sources))
        published = publish_package(
            operation,
            publisher.bind_publisher(FilesystemPublishRequest(target)),
        )
    members = tuple(
        PackCommandMember(
            name=name,
            logical_size=packaged.logical_size,
            chunk_count=packaged.chunk_count,
        )
        for name, packaged in zip(
            member_names,
            published.package.streams,
            strict=True,
        )
    )
    write_pack_result(
        PackCommandResult(
            target=published.publication.reference,
            encoded_size=published.package.encoded_size,
            members=members,
            cleanup_issues=published.publication.cleanup_issues,
        ),
        stdout=context.stdout,
        stderr=context.stderr,
    )
    return EXIT_SUCCESS


def _unpack_path(
    context: CliContext,
    *,
    input_path: str,
    output_directory: str,
) -> int:
    registry = context.registry
    reader_provider = cast(
        CarrierReaderProvider[FilesystemReadRequest],
        registry.require_carrier_reader_provider(FILESYSTEM_CARRIER_ID),
    )
    file_archiver = _file_archiver(registry)
    source_path = Path(input_path)
    windows_origin_not_propagated = _has_windows_origin_mark(source_path)
    carrier = reader_provider.bind_reader(FilesystemReadRequest(source_path))
    source = carrier.open()
    primary_error: BaseException | None = None
    try:
        reader = ContainerReader(source, limits=context.limits)
        result = file_archiver.extract(reader, Path(output_directory))
    except BaseException as error:
        primary_error = error
        raise
    finally:
        close_all(
            ((f"input carrier {source_path}", carrier),),
            primary_error=primary_error,
        )
    write_unpack_result(
        result,
        stdout=context.stdout,
        stderr=context.stderr,
        windows_origin_not_propagated=windows_origin_not_propagated,
    )
    return EXIT_SUCCESS


def _has_windows_origin_mark(path: Path) -> bool:
    if sys.platform != "win32":
        return False
    try:
        with Path(f"{path}:Zone.Identifier").open("rb"):
            return True
    except OSError:
        return False


__all__ = [
    "EXIT_ARCHIVE",
    "EXIT_CARRIER",
    "EXIT_PROFILE",
    "PackCommand",
    "UnpackCommand",
    "obst_commands",
]
