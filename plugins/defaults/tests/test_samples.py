from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from obst.core import (
    ContainerReader,
    ExtensionRegistry,
    RecipeSpec,
    StageSpec,
    materialize_stream,
)
from obst_defaults.carriers import publish_package
from obst_defaults.carriers.filesystem import (
    FilesystemPublisherSession,
    FilesystemPublishRequest,
)
from obst_defaults.codecs.zlib import ZlibExtension, ZlibParameters
from obst_defaults.files import FileArchiver, FileExtension
from obst_defaults.packagers.fixed import (
    FixedPackageRequest,
    FixedPackagerExtension,
)

SAMPLE_ROOT = Path(__file__).parents[3] / "samples"
SAMPLE_PAIRS = (
    ("images/an_vision-gDPaDDy6_WE-unsplash.jpg", "apple.obst"),
    ("images/fernando-andrade-nAOZCYcLND8-unsplash.jpg", "pineapple.obst"),
    ("images/jo-sonn-zeFy-oCUhV8-unsplash.jpg", "fruit-bowl.obst"),
)

_ZLIB_EXTENSION = ZlibExtension()
_FILE_EXTENSION = FileExtension()
_FILE_REGISTRY = ExtensionRegistry((_ZLIB_EXTENSION, _FILE_EXTENSION))
_FILE_ARCHIVER = FileArchiver(_FILE_REGISTRY)
_FILE_RECIPE = RecipeSpec(
    (
        StageSpec(
            _ZLIB_EXTENSION.extension_id,
            _ZLIB_EXTENSION.encode_parameters(ZlibParameters(9)),
        ),
    )
)


def _stage_registry() -> ExtensionRegistry:
    return ExtensionRegistry((_ZLIB_EXTENSION,))


def _sample_registry() -> ExtensionRegistry:
    return _FILE_REGISTRY


def _publish_sample(target: Path, sources: tuple[Path, ...]) -> None:
    with _FILE_ARCHIVER.open_sources(
        sources,
        source_profile_id=_FILE_EXTENSION.extension_id,
        recipe=_FILE_RECIPE,
    ) as logical_sources:
        operation = FixedPackagerExtension().prepare_package(
            FixedPackageRequest(_sample_registry(), logical_sources)
        )
        publish_package(
            operation,
            FilesystemPublisherSession(FilesystemPublishRequest(target)),
        )


def _recover_files(container_path: Path) -> dict[str, bytes]:
    with container_path.open("rb") as source:
        streams = tuple(ContainerReader(source).manifest.streams)

    recovered: dict[str, bytes] = {}
    for stream in streams:
        with container_path.open("rb") as source:
            reader = ContainerReader(source)
            recovered[_FILE_EXTENSION.plan_file(stream.metadata).name] = (
                materialize_stream(reader, stream.stream_id, _stage_registry())
            )
    return recovered


@pytest.mark.parametrize(("source_name", "container_name"), SAMPLE_PAIRS)
def test_image_sample_decodes_byte_identically(
    source_name: str,
    container_name: str,
) -> None:
    source = (SAMPLE_ROOT / source_name).read_bytes()
    with (SAMPLE_ROOT / container_name).open("rb") as encoded:
        reader = ContainerReader(encoded)
        assert (
            reader.manifest.recipes[0].stages[0].stage_id == ZlibExtension.extension_id
        )
        stream = reader.manifest.streams[0]
        assert stream.stream_type == _FILE_EXTENSION.extension_id
        assert _FILE_EXTENSION.plan_file(stream.metadata).name == Path(source_name).name
        assert materialize_stream(reader, 0, _stage_registry()) == source


def test_sample_manifest_matches_checked_in_files() -> None:
    document = cast(
        dict[str, object],
        json.loads((SAMPLE_ROOT / "manifest.json").read_text(encoding="utf-8")),
    )
    images = cast(list[dict[str, object]], document["images"])

    assert len(images) == 10
    for image in images:
        source_path = SAMPLE_ROOT / cast(str, image["path"])
        source = source_path.read_bytes()
        assert image["size"] == len(source)
        assert image["sha256"] == hashlib.sha256(source).hexdigest()
        assert cast(str, image["source_url"]).startswith("https://unsplash.com/photos/")

        container = cast(dict[str, object] | None, image.get("container"))
        if container is not None:
            container_path = SAMPLE_ROOT / cast(str, container["path"])
            encoded = container_path.read_bytes()
            assert container["size"] == len(encoded)
            assert container["sha256"] == hashlib.sha256(encoded).hexdigest()


def test_nested_sample_recovers_checked_in_inner_containers() -> None:
    document = cast(
        dict[str, object],
        json.loads((SAMPLE_ROOT / "manifest.json").read_text(encoding="utf-8")),
    )
    nested = cast(dict[str, object], document["nested_archive"])
    nested_path = SAMPLE_ROOT / cast(str, nested["path"])
    encoded = nested_path.read_bytes()
    expected_names = cast(list[str], nested["members"])

    assert nested["size"] == len(encoded)
    assert nested["sha256"] == hashlib.sha256(encoded).hexdigest()

    recovered = _recover_files(nested_path)

    assert list(recovered) == expected_names
    assert recovered == {
        name: (SAMPLE_ROOT / name).read_bytes() for name in expected_names
    }


@pytest.mark.parametrize(("source_name", "container_name"), SAMPLE_PAIRS)
def test_rebuilt_image_sample_recovers_source(
    source_name: str,
    container_name: str,
    tmp_path: Path,
) -> None:
    rebuilt = tmp_path / container_name
    _publish_sample(rebuilt, (SAMPLE_ROOT / source_name,))

    assert _recover_files(rebuilt) == {
        Path(source_name).name: (SAMPLE_ROOT / source_name).read_bytes()
    }


def test_rebuilt_nested_sample_recovers_inner_containers(tmp_path: Path) -> None:
    rebuilt = tmp_path / "all-fruit.obst"
    sources = tuple(SAMPLE_ROOT / container_name for _, container_name in SAMPLE_PAIRS)
    _publish_sample(rebuilt, sources)

    assert _recover_files(rebuilt) == {
        source.name: source.read_bytes() for source in sources
    }
