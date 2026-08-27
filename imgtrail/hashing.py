"""Perceptual hashing: the backbone of both dedupe and verification."""

from __future__ import annotations

import io

import imagehash
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = 200_000_000


def _open(source: str | bytes | Image.Image) -> Image.Image:
    if isinstance(source, Image.Image):
        return source
    if isinstance(source, bytes):
        return Image.open(io.BytesIO(source))
    return Image.open(source)


def phash(source: str | bytes | Image.Image) -> str:
    with _open(source) as img:
        return str(imagehash.phash(img.convert("RGB"), hash_size=8))


def hamming(a: str, b: str) -> int:
    return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)


def thumbnail_png(source: str | bytes, size: int = 160) -> bytes:
    with _open(source) as img:
        img = img.convert("RGB")
        img.thumbnail((size, size))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def encode_for_api(path: str, max_side: int = 1280) -> bytes:
    """Downscale before upload: Vision resizes internally anyway, and this keeps
    the base64 payload small enough to batch 16 images per request."""
    with _open(path) as img:
        img = img.convert("RGB")
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return buf.getvalue()
