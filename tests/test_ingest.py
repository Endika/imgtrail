from pathlib import Path

from imgtrail import ingest, store

from .conftest import draw


def test_dedupe_collapses_a_recompressed_crop(photos: Path, tmp_path: Path):
    conn = store.connect(tmp_path / "data")
    assert ingest.index(conn, photos, tmp_path / "data") == 3

    assert ingest.assign_groups(conn) == 2  # a.png + its repost are one photo

    pending = store.unsearched_groups(conn)
    assert len(pending) == 2, "a duplicate must not cost a second API call"


def test_index_is_idempotent(photos: Path, tmp_path: Path):
    data = tmp_path / "data"
    conn = store.connect(data)
    ingest.index(conn, photos, data)

    assert ingest.index(conn, photos, data) == 0
    assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 3


def test_profile_pictures_are_skipped(tmp_path: Path):
    export = tmp_path / "export" / "media"
    (export / "posts").mkdir(parents=True)
    (export / "profile").mkdir(parents=True)
    draw(export / "posts" / "post.png", seed=3)
    draw(export / "profile" / "avatar.png", seed=4)

    found = [p.name for p in ingest.discover(tmp_path / "export", tmp_path / "data")]
    assert found == ["post.png"]


def test_reads_a_zip_export(photos: Path, tmp_path: Path):
    import zipfile

    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for image in photos.iterdir():
            zf.write(image, f"media/posts/{image.name}")

    found = list(ingest.discover(archive, tmp_path / "data"))
    assert len(found) == 3
