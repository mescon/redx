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
