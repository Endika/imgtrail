"""Verification runs against a real local HTTP server — no mocked transports."""

import functools
import http.server
import threading
from pathlib import Path

import pytest

from imgtrail import store, verify
from imgtrail.hashing import phash

from .conftest import draw, draw_variant


@pytest.fixture
def server(tmp_path: Path):
    root = tmp_path / "web"
    root.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_hits_are_classified_against_the_original(server, tmp_path: Path):
    root, base = server
    original = draw(tmp_path / "original.png", seed=7)
    draw(root / "same.png", seed=7)
    draw_variant(root / "cropped.jpg", seed=7)
    draw(root / "other.png", seed=1234)

    conn = store.connect(tmp_path / "data")
    store.add_photo(conn, str(original), phash(str(original)))
    conn.execute("UPDATE photos SET group_id = id")
    for name in ("same.png", "cropped.jpg", "other.png", "missing.png"):
        store.add_hit(conn, 1, image_url=f"{base}/{name}", kind="full", domain="127.0.0.1")
    conn.commit()

    verify.verify_pending(conn, workers=4)

    got = {
        Path(r["image_url"]).name: (r["status"], r["distance"])
        for r in conn.execute("SELECT image_url, status, distance FROM hits")
    }
    assert got["same.png"][0] == "confirmed"
    assert got["cropped.jpg"][0] in ("confirmed", "likely")
    assert got["other.png"][0] == "rejected"
    assert got["missing.png"] == ("unreachable", None)


def test_a_non_image_response_is_not_treated_as_a_match(server, tmp_path: Path):
    root, base = server
    (root / "page.html").write_text("<html>not an image</html>")
    original = draw(tmp_path / "original.png", seed=7)

    conn = store.connect(tmp_path / "data")
    store.add_photo(conn, str(original), phash(str(original)))
    conn.execute("UPDATE photos SET group_id = id")
    store.add_hit(conn, 1, image_url=f"{base}/page.html", kind="full", domain="127.0.0.1")
    conn.commit()

    verify.verify_pending(conn, workers=1)

    assert conn.execute("SELECT status FROM hits").fetchone()[0] == "unreachable"


def test_verification_does_not_repeat_itself(server, tmp_path: Path):
    root, base = server
    draw(root / "same.png", seed=7)
    original = draw(tmp_path / "original.png", seed=7)

    conn = store.connect(tmp_path / "data")
    store.add_photo(conn, str(original), phash(str(original)))
    conn.execute("UPDATE photos SET group_id = id")
    store.add_hit(conn, 1, image_url=f"{base}/same.png", kind="full", domain="127.0.0.1")
    conn.commit()

    assert verify.verify_pending(conn) == {"confirmed": 1}
    assert verify.verify_pending(conn) == {}


def test_classify_boundaries():
    assert verify.classify(8) == "confirmed"
    assert verify.classify(9) == "likely"
    assert verify.classify(16) == "likely"
    assert verify.classify(17) == "rejected"
