import random
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


def draw(path: Path, seed: int, size: tuple[int, int] = (400, 400)) -> Path:
    """Deterministic, visually distinct image — distinct seeds give distinct pHashes."""
    rng = random.Random(seed)
    img = Image.new("RGB", size, (rng.randint(0, 255),) * 3)
    pen = ImageDraw.Draw(img)
    for _ in range(12):
        x, y = rng.randint(0, size[0]), rng.randint(0, size[1])
        pen.ellipse(
            [x, y, x + rng.randint(40, 180), y + rng.randint(40, 180)],
            fill=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)),
        )
    img.save(path)
    return path


def draw_variant(path: Path, seed: int) -> Path:
    """The same photo after a crop and a lossy re-encode — what a repost looks like."""
    tmp = path.with_suffix(".src.png")
    draw(tmp, seed)
    with Image.open(tmp) as img:
        w, h = img.size
        img.crop((6, 6, w - 6, h - 6)).save(path, format="JPEG", quality=70)
    tmp.unlink()
    return path


@pytest.fixture
def photos(tmp_path: Path) -> Path:
    album = tmp_path / "album"
    album.mkdir()
    draw(album / "a.png", seed=1)
    draw_variant(album / "a_repost.jpg", seed=1)  # same photo as a.png
    draw(album / "b.png", seed=99)
    return album
