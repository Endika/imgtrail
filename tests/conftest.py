"""Fixtures and in-memory doubles. No mocks: every double is a real, tiny implementation."""

from __future__ import annotations

import io
import random
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from imgtrail.adapters.sqlite_repository import SqliteRepository
from imgtrail.domain import Match


def image_bytes(seed: int, size: tuple[int, int] = (400, 400)) -> bytes:
    """Deterministic and visually distinct: distinct seeds give distinct fingerprints."""
    rng = random.Random(seed)
    canvas = Image.new("RGB", size, (rng.randint(0, 255),) * 3)
    pen = ImageDraw.Draw(canvas)
    for _ in range(12):
        x, y = rng.randint(0, size[0]), rng.randint(0, size[1])
        pen.ellipse(
            [x, y, x + rng.randint(40, 180), y + rng.randint(40, 180)],
            fill=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)),
        )
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def flat_bytes(size: tuple[int, int] = (400, 400)) -> bytes:
    """A frame with nothing in it — a black story, a blank export. pHash has no purchase."""
    buffer = io.BytesIO()
    Image.new("RGB", size, (0, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def repost_bytes(seed: int) -> bytes:
    """The same photo after a crop and a lossy re-encode — what a repost looks like."""
    with Image.open(io.BytesIO(image_bytes(seed))) as original:
        width, height = original.size
        buffer = io.BytesIO()
        original.crop((6, 6, width - 6, height - 6)).save(buffer, format="JPEG", quality=70)
        return buffer.getvalue()


class DictPhotoSource:
    """A PhotoSource and ImageLoader backed by a plain dict."""

    def __init__(self, images: dict[str, bytes]) -> None:
        self.images = images

    def photos(self) -> Iterator[str]:
        yield from sorted(self.images)

    def load(self, reference: str) -> bytes:
        try:
            return self.images[reference]
        except KeyError as missing:
            raise OSError(reference) from missing


class FakeSearchEngine:
    """Answers with canned matches and records exactly what it was asked about."""

    name = "fake"
    batch_size = 2  # small on purpose, so batching is actually exercised

    def __init__(self, answers: Sequence[list[Match]] | None = None) -> None:
        self._answers = list(answers or [])
        self.calls = 0
        self.images_seen: list[bytes] = []

    def search(self, images: Sequence[bytes]) -> list[list[Match]]:
        self.calls += 1
        self.images_seen.extend(images)
        answers: list[list[Match]] = []
        for _ in images:
            answers.append(self._answers.pop(0) if self._answers else [])
        return answers

    def estimated_cost(self, units: int, already_used: int = 0) -> float:
        return 0.0

    def close(self) -> None:
        pass


class DictImageFetcher:
    """Serves candidate images from a dict; anything unknown is unreachable."""

    def __init__(self, downloads: dict[str, bytes | None] | None = None) -> None:
        self.downloads = downloads or {}
        self.requested: list[str] = []

    def fetch(self, url: str) -> bytes | None:
        self.requested.append(url)
        return self.downloads.get(url)


@pytest.fixture
def repository() -> Iterator[SqliteRepository]:
    store = SqliteRepository(":memory:")
    yield store
    store.close()


@pytest.fixture
def album() -> DictPhotoSource:
    """Four files, but only three distinct photos: a.png and a_repost.jpg are the same shot."""
    return DictPhotoSource(
        {
            "/album/a.png": image_bytes(1),
            "/album/a_repost.jpg": repost_bytes(1),
            "/album/b.png": image_bytes(99),
            "/album/c.png": image_bytes(7),
        }
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path
