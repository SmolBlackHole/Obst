"""Build the checked-in OBST image samples and their attribution manifest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from obst.core import (
    DEFAULT_RESOURCE_POLICY,
    PackagerProvider,
    RecipeSpec,
    ResourceAccounting,
    StageSpec,
    format_version,
)
from obst.core.registry import ExtensionRegistry

from obst_defaults.carriers import publish_package
from obst_defaults.carriers.filesystem import (
    FilesystemPublisherSession,
    FilesystemPublishRequest,
)
from obst_defaults.codecs.zlib import ZlibExtension, ZlibParameters
from obst_defaults.files import DEFAULT_FILE_CHUNK_SIZE, FileArchiver, FileExtension
from obst_defaults.packagers import FixedPackageRequest, FixedPackagerExtension

ROOT = Path(__file__).resolve().parents[3]
SAMPLE_ROOT = ROOT / "samples"
IMAGE_ROOT = SAMPLE_ROOT / "images"
MANIFEST_PATH = SAMPLE_ROOT / "manifest.json"
NESTED_ARCHIVE_PATH = SAMPLE_ROOT / "all-fruit.obst"

_ZLIB_EXTENSION = ZlibExtension()
_FILE_EXTENSION = FileExtension()
_FIXED_PACKAGER = FixedPackagerExtension()
_SAMPLE_REGISTRY = ExtensionRegistry(
    (_ZLIB_EXTENSION, _FILE_EXTENSION, _FIXED_PACKAGER)
)
_FILE_ARCHIVER = FileArchiver(_SAMPLE_REGISTRY)
_FIXED_PACKAGER_PROVIDER = cast(
    PackagerProvider[FixedPackageRequest],
    _SAMPLE_REGISTRY.require_packager_provider(_FIXED_PACKAGER.extension_id),
)
_FILE_RECIPE = RecipeSpec(
    (
        StageSpec(
            _ZLIB_EXTENSION.extension_id,
            _ZLIB_EXTENSION.encode_parameters(ZlibParameters(9)),
        ),
    )
)


@dataclass(frozen=True, slots=True)
class Photo:
    filename: str
    title: str
    photographer: str
    photo_id: str
    source_url: str
    container: str | None = None


PHOTOS = (
    Photo(
        "an_vision-gDPaDDy6_WE-unsplash.jpg",
        "Red apple fruit",
        "an_vision",
        "gDPaDDy6_WE",
        "https://unsplash.com/photos/red-apple-fruit-gDPaDDy6_WE",
        "apple.obst",
    ),
    Photo(
        "fernando-andrade-nAOZCYcLND8-unsplash.jpg",
        "Ripe pineapple fruit",
        "Fernando Andrade",
        "nAOZCYcLND8",
        "https://unsplash.com/photos/ripe-pineapple-fruit-nAOZCYcLND8",
        "pineapple.obst",
    ),
    Photo(
        "jo-sonn-zeFy-oCUhV8-unsplash.jpg",
        "Assorted fruits",
        "Jo Sonn",
        "zeFy-oCUhV8",
        "https://unsplash.com/photos/assorted-fruits-zeFy-oCUhV8",
        "fruit-bowl.obst",
    ),
    Photo(
        "mockup-graphics-13PBliWTDng-unsplash.jpg",
        "Sliced watermelon on white background",
        "Mockup Graphics",
        "13PBliWTDng",
        "https://unsplash.com/photos/sliced-watermelon-on-white-background-13PBliWTDng",
    ),
    Photo(
        "mockup-graphics-haSJEJYzl5A-unsplash.jpg",
        "Pear with yellow and red skin",
        "Mockup Graphics",
        "haSJEJYzl5A",
        "https://unsplash.com/photos/pear-with-yellow-and-red-skin-haSJEJYzl5A",
    ),
    Photo(
        "mockup-graphics-jHcKq383ibg-unsplash.jpg",
        "Red raspberry on white background",
        "Mockup Graphics",
        "jHcKq383ibg",
        "https://unsplash.com/photos/red-raspberry-on-white-background-jHcKq383ibg",
    ),
    Photo(
        "mockup-graphics-Kl3467edwsE-unsplash.jpg",
        "Yellow banana on white background",
        "Mockup Graphics",
        "Kl3467edwsE",
        "https://unsplash.com/photos/yellow-banana-on-white-background-Kl3467edwsE",
    ),
    Photo(
        "mockup-graphics-XiWQbLEhFyo-unsplash.jpg",
        "Whole red pomegranate on white",
        "Mockup Graphics",
        "XiWQbLEhFyo",
        "https://unsplash.com/photos/whole-red-pomegranate-on-white-XiWQbLEhFyo",
    ),
    Photo(
        "quaritsch-photography-lZ8onQ1wuY8-unsplash.jpg",
        "Two cherries on white surface",
        "Quaritsch Photography",
        "lZ8onQ1wuY8",
        "https://unsplash.com/photos/two-cherries-on-white-surface-lZ8onQ1wuY8",
    ),
    Photo(
        "tijana-drndarski-ta0b_NDxi6k-unsplash.jpg",
        "Black and red round fruit",
        "Tijana Drndarski",
        "ta0b_NDxi6k",
        "https://unsplash.com/photos/black-and-red-round-fruit-ta0b_NDxi6k",
    ),
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_container(source_path: Path, target_path: Path) -> dict[str, object]:
    with _FILE_ARCHIVER.open_sources(
        (source_path,),
        source_profile_id=_FILE_EXTENSION.extension_id,
        recipe=_FILE_RECIPE,
    ) as sources:
        operation = _FIXED_PACKAGER_PROVIDER.prepare_package(
            FixedPackageRequest(
                _SAMPLE_REGISTRY,
                sources,
                ResourceAccounting(DEFAULT_RESOURCE_POLICY),
            )
        )
        published = publish_package(
            operation,
            FilesystemPublisherSession(
                FilesystemPublishRequest(target_path, overwrite=True)
            ),
        )
    member = published.package.streams[0]
    encoded = target_path.read_bytes()
    return {
        "path": target_path.name,
        "size": len(encoded),
        "sha256": _sha256(encoded),
        "chunk_count": member.chunk_count,
    }


def main() -> None:
    image_entries: list[dict[str, object]] = []
    for photo in PHOTOS:
        source_path = IMAGE_ROOT / photo.filename
        source = source_path.read_bytes()
        entry: dict[str, object] = {
            "path": source_path.relative_to(SAMPLE_ROOT).as_posix(),
            "size": len(source),
            "sha256": _sha256(source),
            "title": photo.title,
            "photographer": photo.photographer,
            "photo_id": photo.photo_id,
            "source_url": photo.source_url,
        }
        if photo.container is not None:
            entry["container"] = _build_container(
                source_path,
                SAMPLE_ROOT / photo.container,
            )
        image_entries.append(entry)

    nested_sources = tuple(
        SAMPLE_ROOT / photo.container for photo in PHOTOS if photo.container is not None
    )
    with _FILE_ARCHIVER.open_sources(
        nested_sources,
        source_profile_id=_FILE_EXTENSION.extension_id,
        recipe=_FILE_RECIPE,
    ) as sources:
        operation = _FIXED_PACKAGER_PROVIDER.prepare_package(
            FixedPackageRequest(
                _SAMPLE_REGISTRY,
                sources,
                ResourceAccounting(DEFAULT_RESOURCE_POLICY),
            )
        )
        nested_result = publish_package(
            operation,
            FilesystemPublisherSession(
                FilesystemPublishRequest(NESTED_ARCHIVE_PATH, overwrite=True)
            ),
        )
    nested_encoded = NESTED_ARCHIVE_PATH.read_bytes()

    document = {
        "schema_version": 1,
        "generated_by": "plugins/defaults/scripts/build_samples.py",
        "image_license": {
            "name": "Unsplash License",
            "url": "https://unsplash.com/license",
            "note": "Applies to the source images, not the OBST project code.",
        },
        "container_defaults": {
            "format": format_version.label,
            "stream_type": _FILE_EXTENSION.extension_id,
            "recipe": _ZLIB_EXTENSION.extension_id,
            "zlib_level": 9,
            "logical_chunk_size": DEFAULT_FILE_CHUNK_SIZE,
        },
        "nested_archive": {
            "path": NESTED_ARCHIVE_PATH.name,
            "size": len(nested_encoded),
            "sha256": _sha256(nested_encoded),
            "members": [
                _FILE_ARCHIVER.plan_file(
                    stream.declaration.stream_type,
                    stream.declaration.metadata,
                ).name
                for stream in nested_result.package.streams
            ],
        },
        "images": image_entries,
    }
    MANIFEST_PATH.write_text(
        json.dumps(document, indent="\t", ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
