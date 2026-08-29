from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerReader,
    ContainerWriter,
    CoreResource,
    CorruptContainerError,
    ExtensionDescriptor,
    ExtensionRegistry,
    Manifest,
    Recipe,
    RecipeSpec,
    ResourceAccounting,
    ResourceLimitError,
    Stream,
    encode_chunk_once,
)
from obst.core.extensions import ExtensionKind

from obst_defaults.carriers import (
    PublicationReceipt,
    PublishedPackage,
    publish_package,
)
from obst_defaults.carriers.filesystem import (
    FilesystemPublisherSession,
    FilesystemPublishRequest,
)
from obst_defaults.files import (
    FileArchiveError,
    FileArchiver,
    FileExtension,
    FileExtractionResult,
    FileMaterialization,
    FileProfileError,
    FileResource,
)
from obst_defaults.packagers.fixed import (
    FixedPackageRequest,
    FixedPackagerExtension,
)
from support_resources import accounting as _accounting


def _identity_recipe() -> RecipeSpec:
    return RecipeSpec(())


def _registry(extension: FileExtension) -> ExtensionRegistry:
    return ExtensionRegistry((extension,))


def _publish(
    archiver: FileArchiver,
    target: Path,
    source_paths: tuple[Path, ...],
    *,
    chunk_size: int = 64 * 1024,
    recipe: RecipeSpec | None = None,
) -> PublishedPackage[PublicationReceipt[Path]]:
    with archiver.open_sources(
        source_paths,
        source_profile_id=FileExtension.extension_id,
        recipe=_identity_recipe() if recipe is None else recipe,
        chunk_size=chunk_size,
    ) as sources:
        operation = FixedPackagerExtension().prepare_package(
            FixedPackageRequest(archiver.registry, sources, _accounting())
        )
        return publish_package(
            operation,
            FilesystemPublisherSession(FilesystemPublishRequest(target)),
        )


def _extract(
    archiver: FileArchiver,
    source: Path,
    output_directory: Path,
    *,
    accounting: ResourceAccounting | None = None,
) -> FileExtractionResult:
    selected_accounting = _accounting() if accounting is None else accounting
    with source.open("rb") as input_file:
        reader = ContainerReader(input_file, accounting=selected_accounting)
        return archiver.extract(
            reader,
            output_directory,
            accounting=selected_accounting,
        )


def test_file_archiver_preserves_names_and_bytes_through_public_composition(
    tmp_path: Path,
) -> None:
    first = tmp_path / "Äpfel.txt"
    second = tmp_path / "pixels.bin"
    first.write_text("fruit\n", encoding="utf-8")
    second.write_bytes(bytes(range(256)) * 20)
    archive = tmp_path / "selection.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)

    published = _publish(
        archiver,
        archive,
        (first, second),
        chunk_size=257,
    )

    assert published.publication.reference == archive
    assert published.package.encoded_size == archive.stat().st_size
    assert [stream.chunk_count for stream in published.package.streams] == [1, 20]
    with archive.open("rb") as source:
        reader = ContainerReader(source, accounting=_accounting())
        assert [stream.stream_type for stream in reader.manifest.streams] == [
            extension.extension_id,
            extension.extension_id,
        ]
        assert [
            extension.plan_file(stream.metadata).name
            for stream in reader.manifest.streams
        ] == ["Äpfel.txt", "pixels.bin"]

    output = tmp_path / "restored"
    extraction = _extract(archiver, archive, output)

    assert [path.name for path in extraction.paths] == ["Äpfel.txt", "pixels.bin"]
    assert extraction.output_directory == output
    assert (output / "Äpfel.txt").read_bytes() == first.read_bytes()
    assert (output / "pixels.bin").read_bytes() == second.read_bytes()


def test_file_archiver_materializes_mixed_profile_ids(tmp_path: Path) -> None:
    class AlternateFileMaterializer:
        extension_id = "org.example/alternate-file@1"
        kind = ExtensionKind.STREAM_PROFILE
        descriptor = ExtensionDescriptor(display_name="Alternate file")

        def plan_file(self, metadata: bytes, /) -> FileMaterialization:
            return FileMaterialization(metadata.removeprefix(b"alt:").decode())

    standard = FileExtension()
    alternate = AlternateFileMaterializer()
    registry = ExtensionRegistry((standard, alternate))
    archiver = FileArchiver(registry)
    manifest = Manifest(
        recipes=(Recipe(0, ()),),
        streams=(
            Stream(0, standard.extension_id, 0, standard.encode_file_name("a.txt")),
            Stream(1, alternate.extension_id, 0, b"alt:b.rar"),
        ),
    )
    archive = tmp_path / "mixed.obst"
    with archive.open("wb") as target:
        writer = ContainerWriter(target, manifest, accounting=_accounting())
        for stream_id, payload in enumerate((b"standard", b"rar bytes")):
            writer.write_chunk(
                encode_chunk_once(
                    payload,
                    stream_id=stream_id,
                    sequence=0,
                    recipe=manifest.recipe(0),
                    registry=registry,
                    accounting=_accounting(),
                )
            )
        writer.finish()

    result = _extract(archiver, archive, tmp_path / "output")

    assert tuple(path.name for path in result.paths) == ("a.txt", "b.rar")
    assert result.paths[0].read_bytes() == b"standard"
    assert result.paths[1].read_bytes() == b"rar bytes"


def test_file_archiver_uses_only_the_recipe_supplied_by_its_caller(
    tmp_path: Path,
) -> None:
    source = tmp_path / "apple.txt"
    source.write_bytes(b"red")
    extension = FileExtension()
    recipe = _identity_recipe()
    archiver = FileArchiver(_registry(extension))

    published = _publish(
        archiver,
        tmp_path / "apple.obst",
        (source,),
        recipe=recipe,
    )

    assert published.package.manifest.recipes[0].stages == recipe.stages


def test_file_sources_read_from_the_handle_opened_during_planning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "payload.bin"
    source_path.write_bytes(b"opened once")
    extension = FileExtension()
    archiver = FileArchiver(_registry(extension))

    with archiver.open_sources(
        (source_path,),
        source_profile_id=extension.extension_id,
        recipe=_identity_recipe(),
        chunk_size=4,
    ) as sources:

        def refuse_reopen(*args: object, **kwargs: object) -> int:
            raise AssertionError("file source was reopened")

        monkeypatch.setattr("obst_defaults.files.adapter.os.open", refuse_reopen)
        assert tuple(sources[0].iter_chunks()) == (b"open", b"ed o", b"nce")

    renamed = tmp_path / "closed.bin"
    source_path.rename(renamed)
    assert renamed.read_bytes() == b"opened once"


def test_empty_file_is_preserved_without_chunks(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.touch()
    archive = tmp_path / "empty.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)

    published = _publish(archiver, archive, (empty,))
    extraction = _extract(archiver, archive, tmp_path / "output")

    assert published.package.streams[0].chunk_count == 0
    assert extraction.paths[0].read_bytes() == b""


def test_extraction_member_limit_refuses_chunkless_fanout_before_output(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.touch()
    second.touch()
    archive = tmp_path / "empty-files.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _publish(archiver, archive, (first, second))
    output = tmp_path / "output"

    with pytest.raises(ResourceLimitError) as error:
        _extract(
            archiver,
            archive,
            output,
            accounting=_accounting((FileResource.ARCHIVE_MEMBERS, 1)),
        )

    assert error.value.resource is FileResource.ARCHIVE_MEMBERS
    assert not output.exists()


def test_extraction_byte_limits_accept_boundary_and_publish_nothing_above_it(
    tmp_path: Path,
) -> None:
    source = tmp_path / "payload.bin"
    source.write_bytes(b"12345678")
    archive = tmp_path / "payload.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _publish(archiver, archive, (source,), chunk_size=4)

    exact_output = tmp_path / "exact"
    _extract(
        archiver,
        archive,
        exact_output,
        accounting=_accounting(
            (FileResource.ARCHIVE_MEMBER_BYTES, 8),
            (FileResource.ARCHIVE_TOTAL_BYTES, 8),
        ),
    )
    assert (exact_output / source.name).read_bytes() == source.read_bytes()

    rejected_output = tmp_path / "rejected"
    with pytest.raises(ResourceLimitError) as error:
        _extract(
            archiver,
            archive,
            rejected_output,
            accounting=_accounting((FileResource.ARCHIVE_MEMBER_BYTES, 7)),
        )
    assert error.value.resource is FileResource.ARCHIVE_MEMBER_BYTES
    assert rejected_output.is_dir()
    assert list(rejected_output.iterdir()) == []


def test_streaming_extraction_does_not_materialize_whole_streams(
    tmp_path: Path,
) -> None:
    source = tmp_path / "payload.bin"
    source.write_bytes(b"stream me")
    archive = tmp_path / "payload.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _publish(archiver, archive, (source,), chunk_size=3)

    _extract(
        archiver,
        archive,
        tmp_path / "output",
        accounting=_accounting((CoreResource.MATERIALIZED_STREAM_BYTES, 0)),
    )

    assert (tmp_path / "output" / source.name).read_bytes() == source.read_bytes()


def test_sources_reject_duplicate_portable_basenames(tmp_path: Path) -> None:
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"
    first_directory.mkdir()
    second_directory.mkdir()
    first = first_directory / "Fruit.txt"
    second = second_directory / "fruit.TXT"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    extension = FileExtension()
    archiver = FileArchiver(_registry(extension))

    with pytest.raises(FileArchiveError, match="duplicate portable filename"):
        with archiver.open_sources(
            (first, second),
            source_profile_id=extension.extension_id,
            recipe=_identity_recipe(),
        ):
            pass


def test_extract_rejects_path_traversal_before_creating_output(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "unsafe.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _write_profile_container(
        archive,
        extension.extension_id,
        b"../escape.txt",
        b"bad",
        registry,
    )
    output = tmp_path / "output"

    with pytest.raises(FileProfileError, match="non-portable path character"):
        _extract(archiver, archive, output)

    assert not output.exists()
    assert not (tmp_path / "escape.txt").exists()


def test_extract_rejects_non_file_streams(tmp_path: Path) -> None:
    archive = tmp_path / "bytes.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _write_profile_container(archive, BYTES_STREAM_TYPE, b"", b"data", registry)

    with pytest.raises(FileArchiveError, match="no active file materializer"):
        _extract(archiver, archive, tmp_path / "output")


def test_extract_never_overwrites_existing_files(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_bytes(b"new")
    archive = tmp_path / "notes.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _publish(archiver, archive, (source,))
    output = tmp_path / "output"
    output.mkdir()
    existing = output / "notes.txt"
    existing.write_bytes(b"keep")

    with pytest.raises(FileArchiveError, match="refusing to overwrite"):
        _extract(archiver, archive, output)

    assert existing.read_bytes() == b"keep"


def test_extract_treats_a_dangling_symlink_as_an_existing_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "notes.txt"
    source.write_bytes(b"new")
    archive = tmp_path / "notes.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _publish(archiver, archive, (source,))
    output = tmp_path / "output"
    output.mkdir()
    target = output / source.name
    try:
        target.symlink_to(output / "missing-target")
    except OSError:
        pytest.skip("temporary filesystem does not permit symbolic links")

    with pytest.raises(FileArchiveError, match="refusing to overwrite"):
        _extract(archiver, archive, output)

    assert target.is_symlink()


def test_extract_rejects_a_windows_reparse_point_output_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload")
    archive = tmp_path / "payload.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _publish(archiver, archive, (source,))
    output = tmp_path / "output"
    output.mkdir()
    original_lstat = os.lstat

    def reparse_lstat(path: os.PathLike[str] | str) -> os.stat_result:
        status = original_lstat(path)
        if Path(path) != output:
            return status
        return cast(
            os.stat_result,
            SimpleNamespace(
                st_mode=status.st_mode,
                st_dev=status.st_dev,
                st_ino=status.st_ino,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            ),
        )

    monkeypatch.setattr("obst_defaults.files.adapter.os.lstat", reparse_lstat)

    with pytest.raises(FileArchiveError, match="reparse-point extraction targets"):
        _extract(archiver, archive, output)

    assert list(output.iterdir()) == []


def test_extraction_cleans_temporary_state_when_root_identity_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload")
    archive = tmp_path / "payload.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _publish(archiver, archive, (source,))
    output = tmp_path / "output"

    def reject_changed_root(
        output_directory: Path,
        _expected_identity: tuple[int, int],
    ) -> None:
        assert output_directory == output
        raise FileArchiveError("extraction target changed")

    monkeypatch.setattr(
        "obst_defaults.files.adapter._require_directory_identity",
        reject_changed_root,
    )

    with pytest.raises(FileArchiveError, match="extraction target changed"):
        _extract(archiver, archive, output)

    assert output.is_dir()
    assert list(output.iterdir()) == []


def test_extraction_restores_script_bytes_without_executing_them(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "executed.txt"
    source = tmp_path / "untrusted.cmd"
    source.write_text(f"@echo executed > {marker}\n", encoding="utf-8")
    archive = tmp_path / "script.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _publish(archiver, archive, (source,))

    result = _extract(archiver, archive, tmp_path / "output")

    assert result.paths[0].read_bytes() == source.read_bytes()
    assert not marker.exists()


def test_corruption_never_publishes_partial_files(tmp_path: Path) -> None:
    source = tmp_path / "payload.bin"
    source.write_bytes(bytes(range(256)) * 20)
    archive = tmp_path / "payload.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _publish(archiver, archive, (source,), chunk_size=257)
    corrupted = bytearray(archive.read_bytes())
    corrupted[-1] ^= 0xFF
    archive.write_bytes(corrupted)
    output = tmp_path / "output"

    with pytest.raises(CorruptContainerError):
        _extract(archiver, archive, output)

    assert output.is_dir()
    assert list(output.iterdir()) == []


def test_extraction_preserves_primary_error_when_rollback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    archive = tmp_path / "files.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _publish(archiver, archive, (first, second))
    output = tmp_path / "output"
    publication_count = 0

    def fail_second_publication(
        source: Path,
        target: Path,
    ) -> None:
        nonlocal publication_count
        publication_count += 1
        if publication_count == 2:
            raise RuntimeError("primary publication failure")
        target.write_bytes(source.read_bytes())

    original_unlink = Path.unlink

    def fail_first_rollback(path: Path, missing_ok: bool = False) -> None:
        if path == output / first.name:
            raise OSError("rollback failure")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(
        "obst_defaults.files.adapter._publish_extracted_file",
        fail_second_publication,
    )
    monkeypatch.setattr(Path, "unlink", fail_first_rollback)

    with pytest.raises(RuntimeError, match="primary publication failure") as error:
        _extract(archiver, archive, output)

    assert (output / first.name).exists()
    assert any("rollback failure" in note for note in error.value.__notes__)


def test_extraction_reports_temporary_cleanup_after_successful_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "payload.txt"
    source.write_bytes(b"complete")
    archive = tmp_path / "payload.obst"
    extension = FileExtension()
    registry = _registry(extension)
    archiver = FileArchiver(registry)
    _publish(archiver, archive, (source,))
    output = tmp_path / "output"
    original_rmtree = shutil.rmtree

    def fail_temporary_cleanup(path: Path) -> None:
        raise OSError("cleanup failed")

    monkeypatch.setattr(
        "obst_defaults.files.adapter.shutil.rmtree",
        fail_temporary_cleanup,
    )

    result = _extract(archiver, archive, output)

    assert (output / source.name).read_bytes() == b"complete"
    assert result.cleanup_issues[0].reason == "cleanup failed"
    temporary_root = Path(result.cleanup_issues[0].resource)
    monkeypatch.setattr(
        "obst_defaults.files.adapter.shutil.rmtree",
        original_rmtree,
    )
    shutil.rmtree(temporary_root)


def _write_profile_container(
    path: Path,
    stream_type: str,
    metadata: bytes,
    payload: bytes,
    registry: ExtensionRegistry,
) -> None:
    manifest = Manifest(
        recipes=(Recipe(0, ()),),
        streams=(Stream(0, stream_type, 0, metadata),),
    )
    with path.open("wb") as target:
        writer = ContainerWriter(target, manifest, accounting=_accounting())
        writer.write_chunk(
            encode_chunk_once(
                payload,
                stream_id=0,
                sequence=0,
                recipe=manifest.recipe(0),
                registry=registry,
                accounting=_accounting(),
            )
        )
        writer.finish()
