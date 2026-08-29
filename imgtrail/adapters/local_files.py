"""Reads photos from an Instagram export archive or any folder of images."""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path

EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"})

SKIP_DIRECTORIES = frozenset({"profile", "messages", "stories_activity", "avatars"})
"""The export ships avatars and conversations next to your own pictures.

`media/other` is not one of them: despite the name it holds the bulk of your own
photography — in a real export, 845 pictures against 74 under `media/posts`."""


class FileImageLoader:
    """Reads a photo back from disk. A reference is an absolute path."""

    def load(self, reference: str) -> bytes:
        return Path(reference).read_bytes()


class LocalPhotoSource(FileImageLoader):
    """Implements both PhotoSource and ImageLoader; a reference is an absolute path."""

    def __init__(self, source: Path, workspace: Path) -> None:
        self._source = source
        self._workspace = workspace

    def photos(self) -> Iterator[str]:
        root = self._unpacked()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                continue
            if SKIP_DIRECTORIES & {part.lower() for part in path.relative_to(root).parts}:
                continue
            yield str(path.resolve())

    def _unpacked(self) -> Path:
        if self._source.is_file() and self._source.suffix.lower() == ".zip":
            target = self._workspace / "extracted"
            if not target.exists():
                with zipfile.ZipFile(self._source) as archive:
                    archive.extractall(target)
            return target
        return self._source
