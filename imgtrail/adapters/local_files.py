"""Reads photos from an Instagram export archive or any folder of images."""

from __future__ import annotations

import os
import zipfile
from collections import Counter
from collections.abc import Iterator, Mapping
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
        self._taken = 0
        self._skipped: Counter[str] = Counter()

    def photos(self) -> Iterator[str]:
        root = self._unpacked()
        self._taken = 0
        self._skipped.clear()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                continue
            passed_over = SKIP_DIRECTORIES & {part.lower() for part in path.relative_to(root).parts}
            if passed_over:
                self._skipped[min(passed_over)] += 1
                continue
            self._taken += 1
            yield str(path.resolve())

    @property
    def prefix(self) -> str:
        """Every reference this source yields starts with this.

        It is what keeps a scan to the folder you named: without it, pointing at seven
        photos plans a search over every photo the database has ever seen."""
        return f"{self._unpacked().resolve()}{os.sep}"

    @property
    def taken(self) -> int:
        """Pictures handed over by the last pass. Read it once `photos()` is exhausted."""
        return self._taken

    @property
    def skipped(self) -> Mapping[str, int]:
        """Pictures the last pass passed over, by the folder that caused it.

        A silent skip is how this tool once missed 845 of its owner's photographs, so
        every picture the source declines to hand over is counted and said out loud."""
        return dict(self._skipped)

    def _unpacked(self) -> Path:
        if self._source.is_file() and self._source.suffix.lower() == ".zip":
            target = self._workspace / "extracted"
            if not target.exists():
                with zipfile.ZipFile(self._source) as archive:
                    archive.extractall(target)
            return target
        return self._source
