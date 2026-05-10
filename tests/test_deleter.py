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


def test_subdir_detection_falls_back_to_lstat_when_is_dir_lies(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """SAFETY: If Path.is_dir lies (returns False for a real directory),
    the lstat fallback must still detect the subdir and refuse deletion.

    Real-world incident: a CIFS-mounted parent was atomically trashed
    along with surviving child directories because is_dir under load
    returned False for the children. The dual-check guard is what
    prevents this from recurring.
    """
    target = tmp_path / "parent"
    target.mkdir()
    (target / "child_subdir").mkdir()  # a real, undeniable directory

    # Force every Path.is_dir() to lie and report False. Only lstat
    # remains honest.
    monkeypatch.setattr(Path, "is_dir", lambda self, *a, **kw: False)

    cfg = Config(delete_mode=DeleteMode.DIRECT)
    results = Deleter(cfg).delete_all([target])
    assert not results[0].success, (
        "lstat fallback should have caught the lying is_dir and refused"
    )
    assert (target / "child_subdir").exists()
    assert target.exists()


def test_subdir_detection_treats_symlink_to_dir_as_file_like(
    tmp_path: Path
) -> None:
    """Symlinks (even to directories) must NOT be treated as subdirs;
    they get ignore-pattern classification like files."""
    target = tmp_path / "with_symlink"
    target.mkdir()
    real = tmp_path / "external_real"
    real.mkdir()
    (target / "linked").symlink_to(real, target_is_directory=True)

    # Without an ignore pattern matching "linked", it counts as real,
    # blocking deletion. That's correct: a symlink the user didn't
    # opt into ignoring is a thing they care about.
    cfg = Config(delete_mode=DeleteMode.DIRECT, ignore_files=[])
    results = Deleter(cfg).delete_all([target])
    assert not results[0].success
    assert target.exists()

    # WITH an ignore pattern matching the link name, the dir is empty
    # under our rules and the link gets unlinked along with the parent.
    target2 = tmp_path / "with_symlink_ignored"
    target2.mkdir()
    (target2 / "linked").symlink_to(real, target_is_directory=True)
    cfg = Config(delete_mode=DeleteMode.DIRECT, ignore_files=["linked"])
    results = Deleter(cfg).delete_all([target2])
    assert results[0].success
    assert not target2.exists()
    # The symlink's target must NOT be touched
    assert real.exists()


def test_simulate_handles_post_order_cascade(tmp_path: Path) -> None:
    """SIMULATE must report all five dirs in a/b/c/d/e cascade as 'ok'.

    Real delete modes succeed cumulatively because each rmdir/send2trash
    physically removes the child, so when the parent's race-check runs
    the dir is empty for real. SIMULATE doesn't touch the filesystem, so
    a naive race-check would see the child still present and falsely
    report "No longer empty (race)" for every parent. The deleter
    maintains a per-run set of pretend-deleted paths to keep cascades
    consistent with the scanner's classification.
    """
    deepest = tmp_path / "a" / "b" / "c" / "d" / "e"
    deepest.mkdir(parents=True)
    cfg = Config(delete_mode=DeleteMode.SIMULATE)
    # Post-order: deepest first, root last.
    paths = [
        deepest,
        deepest.parent,
        deepest.parent.parent,
        deepest.parent.parent.parent,
        deepest.parent.parent.parent.parent,
    ]
    results = Deleter(cfg).delete_all(paths)
    failed = [(r.path, r.error) for r in results if not r.success]
    assert not failed, f"unexpected failures in simulate cascade: {failed}"
    assert deepest.exists(), "simulate must NOT physically delete anything"


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
