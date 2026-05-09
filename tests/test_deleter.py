from __future__ import annotations

from pathlib import Path

from redx.config import Config, DeleteMode
from redx.deleter import Deleter


def test_simulate_does_not_delete(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    results = Deleter(Config(delete_mode=DeleteMode.SIMULATE)).delete_all([target])
    assert results[0].success
    assert target.exists()


def test_direct_deletes_empty(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    results = Deleter(Config(delete_mode=DeleteMode.DIRECT)).delete_all([target])
    assert results[0].success
    assert not target.exists()


def test_direct_skips_non_empty(tmp_path: Path) -> None:
    target = tmp_path / "notempty"
    target.mkdir()
    (target / "f.dat").write_text("x")
    results = Deleter(Config(delete_mode=DeleteMode.DIRECT)).delete_all([target])
    assert not results[0].success
    assert target.exists()


def test_direct_post_order_cascade(tmp_path: Path) -> None:
    """Deepest-first order is required: Deleter doesn't sort, caller does."""
    a = tmp_path / "a"
    b = a / "b"
    c = b / "c"
    c.mkdir(parents=True)
    # Post-order: c, b, a
    results = Deleter(Config(delete_mode=DeleteMode.DIRECT)).delete_all([c, b, a])
    assert all(r.success for r in results)
    assert not a.exists()


def test_confirm_callback_can_decline(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    cfg = Config(delete_mode=DeleteMode.TRASH_CONFIRM)
    deleter = Deleter(cfg, on_confirm=lambda p: False)
    results = deleter.delete_all([target])
    assert not results[0].success
    assert target.exists()


def test_direct_deletes_dir_with_only_ignored_files(tmp_path: Path) -> None:
    """The headline scenario from real-world use: a dir holding only
    junk files (matching ignore_files) is classified empty by the
    scanner. Direct delete must unlink the junk and then rmdir."""
    target = tmp_path / "with_junk"
    target.mkdir()
    (target / "thumb.jpg").write_bytes(b"jpg")
    (target / "metadata.nfo").write_text("nfo")
    cfg = Config(
        delete_mode=DeleteMode.DIRECT,
        ignore_files=["*.jpg", "*.nfo"],
    )
    results = Deleter(cfg).delete_all([target])
    assert results[0].success, results[0].error
    assert not target.exists()


def test_direct_skips_when_real_file_present_alongside_ignored(tmp_path: Path) -> None:
    """A real file mixed in still blocks deletion (race protection)."""
    target = tmp_path / "mixed"
    target.mkdir()
    (target / "thumb.jpg").write_bytes(b"jpg")
    (target / "important.dat").write_text("important")
    cfg = Config(
        delete_mode=DeleteMode.DIRECT,
        ignore_files=["*.jpg"],
    )
    results = Deleter(cfg).delete_all([target])
    assert not results[0].success
    assert target.exists()
    assert (target / "important.dat").exists()
    assert (target / "thumb.jpg").exists()  # nothing should be unlinked on a fail


def test_direct_skips_when_real_subdir_present(tmp_path: Path) -> None:
    """A real subdir that wasn't already deleted is treated as a race."""
    target = tmp_path / "with_subdir"
    target.mkdir()
    (target / "leftover_subdir").mkdir()
    cfg = Config(delete_mode=DeleteMode.DIRECT, ignore_files=["*.jpg"])
    results = Deleter(cfg).delete_all([target])
    assert not results[0].success
    assert target.exists()


def test_simulate_does_not_unlink_ignored_files(tmp_path: Path) -> None:
    """Simulate mode must be a true dry-run, even with ignored files present."""
    target = tmp_path / "with_junk"
    target.mkdir()
    junk = target / "thumb.jpg"
    junk.write_bytes(b"jpg")
    cfg = Config(
        delete_mode=DeleteMode.SIMULATE,
        ignore_files=["*.jpg"],
    )
    results = Deleter(cfg).delete_all([target])
    assert results[0].success
    assert target.exists()
    assert junk.exists()
