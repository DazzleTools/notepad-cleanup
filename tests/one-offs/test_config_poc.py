"""POC tests for the config system.

Tests the unified folder registry, ... expansion, MRU, and role management.
Uses a temporary config file to avoid polluting the real config.
"""

import json
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from notepad_cleanup.config import (
    _clean_path,
    load_config, save_config, config_get, config_set, config_unset,
    get_folders, add_folder, remove_folder,
    set_output_folder, get_output_folder_index,
    get_search_folder_indices, add_search_folder, remove_search_folder,
    set_search_folders,
    get_default_output_dir, get_search_dirs,
    get_last_extract, set_last_extract, get_mru_list,
    expand_dots, resolve_path_value,
    _get_config_path, ConfigManager, _set_manager,
)


def with_temp_config(func):
    """Decorator: run test with a temporary config file using ConfigManager."""
    def wrapper(*args, **kwargs):
        with tempfile.TemporaryDirectory(prefix="nc_cfg_") as tmpdir:
            fake_config = Path(tmpdir) / ".notepad-cleanup.json"
            mgr = ConfigManager(config_path=fake_config)
            _set_manager(mgr)
            try:
                return func(tmpdir, *args, **kwargs)
            finally:
                _set_manager(ConfigManager())  # Restore default
    return wrapper


@with_temp_config
def test_empty_config(tmpdir):
    """Fresh config has no folders."""
    assert get_folders() == []
    assert get_search_dirs() == []
    assert get_last_extract() is None
    print("[OK] empty config")


@with_temp_config
def test_add_folders(tmpdir):
    """Adding folders builds the registry."""
    d1 = Path(tmpdir) / "folder1"
    d2 = Path(tmpdir) / "folder2"
    d1.mkdir()
    d2.mkdir()

    idx1 = add_folder(str(d1))
    idx2 = add_folder(str(d2))

    assert idx1 == 0
    assert idx2 == 1
    assert len(get_folders()) == 2
    print("[OK] add folders")


@with_temp_config
def test_add_duplicate(tmpdir):
    """Adding same folder twice returns existing index."""
    d1 = Path(tmpdir) / "folder1"
    d1.mkdir()

    idx1 = add_folder(str(d1))
    idx2 = add_folder(str(d1))

    assert idx1 == idx2 == 0
    assert len(get_folders()) == 1
    print("[OK] add duplicate")


@with_temp_config
def test_remove_folder(tmpdir):
    """Removing a folder renumbers indices."""
    d1 = Path(tmpdir) / "folder1"
    d2 = Path(tmpdir) / "folder2"
    d3 = Path(tmpdir) / "folder3"
    d1.mkdir(); d2.mkdir(); d3.mkdir()

    add_folder(str(d1))
    add_folder(str(d2))
    add_folder(str(d3))
    assert len(get_folders()) == 3

    remove_folder(1)  # Remove folder2
    folders = get_folders()
    assert len(folders) == 2
    assert _clean_path(str(d1)) == _clean_path(folders[0])
    assert _clean_path(str(d3)) == _clean_path(folders[1])
    print("[OK] remove folder renumbers")


@with_temp_config
def test_output_always_index_zero(tmpdir):
    """Setting output moves folder to position 0."""
    d1 = Path(tmpdir) / "folder1"
    d2 = Path(tmpdir) / "folder2"
    d1.mkdir(); d2.mkdir()

    add_folder(str(d1))
    add_folder(str(d2))

    # Initially folder1 is output (index 0)
    assert get_output_folder_index() == 0
    assert _clean_path(get_folders()[0]) == _clean_path(str(d1))

    # Change output to folder2
    set_output_folder(1)

    # folder2 should now be at index 0
    assert get_output_folder_index() == 0
    assert _clean_path(get_folders()[0]) == _clean_path(str(d2))
    assert _clean_path(get_folders()[1]) == _clean_path(str(d1))
    print("[OK] output always index 0")


@with_temp_config
def test_search_folders_independent(tmpdir):
    """Search folders are independently assigned, not all-by-default."""
    d1 = Path(tmpdir) / "folder1"
    d2 = Path(tmpdir) / "folder2"
    d3 = Path(tmpdir) / "folder3"
    d1.mkdir(); d2.mkdir(); d3.mkdir()

    add_folder(str(d1))
    add_folder(str(d2))
    add_folder(str(d3))

    # No search dirs by default
    assert get_search_folder_indices() == []
    assert get_search_dirs() == []

    # Add folder2 as search
    add_search_folder(1)
    assert get_search_folder_indices() == [1]
    assert len(get_search_dirs()) == 1

    # Add folder3 as search
    add_search_folder(2)
    assert get_search_folder_indices() == [1, 2]
    assert len(get_search_dirs()) == 2

    # folder1 (output) is NOT in search
    assert 0 not in get_search_folder_indices()
    print("[OK] search folders independent")


@with_temp_config
def test_remove_search_folder(tmpdir):
    """Removing a search folder keeps others intact."""
    d1 = Path(tmpdir) / "folder1"
    d2 = Path(tmpdir) / "folder2"
    d1.mkdir(); d2.mkdir()

    add_folder(str(d1))
    add_folder(str(d2))
    add_search_folder(0)
    add_search_folder(1)
    assert get_search_folder_indices() == [0, 1]

    remove_search_folder(0)
    assert get_search_folder_indices() == [1]
    print("[OK] remove search folder")


@with_temp_config
def test_clear_search_folders(tmpdir):
    """set_search_folders([]) clears all."""
    d1 = Path(tmpdir) / "folder1"
    d1.mkdir()
    add_folder(str(d1))
    add_search_folder(0)
    assert get_search_folder_indices() == [0]

    set_search_folders([])
    assert get_search_folder_indices() == []
    print("[OK] clear search folders")


@with_temp_config
def test_remove_folder_adjusts_search(tmpdir):
    """Removing a folder adjusts search_folders indices."""
    d1 = Path(tmpdir) / "folder1"
    d2 = Path(tmpdir) / "folder2"
    d3 = Path(tmpdir) / "folder3"
    d1.mkdir(); d2.mkdir(); d3.mkdir()

    add_folder(str(d1))
    add_folder(str(d2))
    add_folder(str(d3))
    add_search_folder(1)
    add_search_folder(2)
    assert get_search_folder_indices() == [1, 2]

    # Remove folder2 (index 1) -- folder3 shifts from 2 to 1
    remove_folder(1)
    indices = get_search_folder_indices()
    assert 1 in indices, f"Expected 1 in {indices} (folder3 shifted down)"
    assert len(indices) == 1, f"Expected 1 entry, got {indices} (folder2 removed from search)"
    print("[OK] remove folder adjusts search indices")


@with_temp_config
def test_expand_dots_basic(tmpdir):
    """... expands to output folder, ...N to folder by index."""
    d1 = Path(tmpdir) / "output"
    d2 = Path(tmpdir) / "search"
    d1.mkdir(); d2.mkdir()

    add_folder(str(d1))
    add_folder(str(d2))

    expanded_0 = expand_dots("...")
    expanded_1 = expand_dots("...1")

    assert _clean_path(str(d1)) == _clean_path(expanded_0)
    assert _clean_path(str(d2)) == _clean_path(expanded_1)
    print("[OK] expand_dots basic")


@with_temp_config
def test_expand_dots_with_subpath(tmpdir):
    """... expansion works inline with subpaths."""
    d1 = Path(tmpdir) / "output"
    d1.mkdir()
    add_folder(str(d1))

    # Note: using forward slashes to avoid escape issues
    expanded = expand_dots("..." + "/subdir/file.txt")
    assert "subdir" in expanded
    assert "file.txt" in expanded
    print("[OK] expand_dots with subpath")


@with_temp_config
def test_expand_dots_negative(tmpdir):
    """...-N expands to MRU entries."""
    d1 = Path(tmpdir) / "output"
    d1.mkdir()
    add_folder(str(d1))

    ext1 = Path(tmpdir) / "extraction1"
    ext2 = Path(tmpdir) / "extraction2"
    ext1.mkdir(); ext2.mkdir()

    set_last_extract(ext1)
    set_last_extract(ext2)  # ext2 is now ...-1, ext1 is ...-2

    expanded_1 = expand_dots("...-1")
    expanded_2 = expand_dots("...-2")

    assert _clean_path(str(ext2)) == _clean_path(expanded_1)
    assert _clean_path(str(ext1)) == _clean_path(expanded_2)
    print("[OK] expand_dots negative (MRU)")


@with_temp_config
def test_expand_dots_unresolved(tmpdir):
    """Unresolvable ...N stays as-is in the output."""
    expanded = expand_dots("...99")
    assert "...99" in expanded
    print("[OK] expand_dots unresolved")


@with_temp_config
def test_mru_depth(tmpdir):
    """MRU respects configured depth."""
    config_set("mru_depth", 3)

    for i in range(5):
        d = Path(tmpdir) / f"extract{i}"
        d.mkdir()
        set_last_extract(d)

    mru = get_mru_list()
    assert len(mru) == 3, f"Expected 3, got {len(mru)}: {mru}"
    # Most recent should be extract4
    assert "extract4" in mru[0]
    assert "extract3" in mru[1]
    assert "extract2" in mru[2]
    print("[OK] MRU depth cap")


@with_temp_config
def test_mru_dedup(tmpdir):
    """Re-extracting to same path moves it to front, no duplicate."""
    ext1 = Path(tmpdir) / "ext1"
    ext2 = Path(tmpdir) / "ext2"
    ext1.mkdir(); ext2.mkdir()

    set_last_extract(ext1)
    set_last_extract(ext2)
    set_last_extract(ext1)  # Re-add ext1

    mru = get_mru_list()
    assert len(mru) == 2
    assert "ext1" in mru[0]  # Most recent
    assert "ext2" in mru[1]
    print("[OK] MRU dedup")


@with_temp_config
def test_clean_path(tmpdir):
    """Stray quotes and trailing backslashes are cleaned."""
    assert _clean_path('C:\\path"') == _clean_path("C:\\path")
    assert _clean_path("'C:\\path'") == _clean_path("C:\\path")
    assert _clean_path('  C:\\path  ') == _clean_path("C:\\path")
    print("[OK] clean_path_str")


@with_temp_config
def test_resolve_path_value_expands_dots(tmpdir):
    """resolve_path_value expands ... and resolves."""
    d1 = Path(tmpdir) / "output"
    d1.mkdir()
    add_folder(str(d1))

    resolved = resolve_path_value("...")
    assert _clean_path(str(d1)) == _clean_path(resolved)
    print("[OK] resolve_path_value expands dots")


def test_migrate_old_config():
    """Old output_dir + search_dirs format migrates to folders."""
    with tempfile.TemporaryDirectory(prefix="nc_mig_") as tmpdir:
        fake_config = Path(tmpdir) / ".notepad-cleanup.json"
        d1 = Path(tmpdir) / "old_output"
        d2 = Path(tmpdir) / "old_search"
        d1.mkdir(); d2.mkdir()

        old_config = {
            "output_dir": str(d1),
            "search_dirs": [str(d2)],
            "diff_tool": "bcomp"
        }
        fake_config.write_text(json.dumps(old_config), encoding="utf-8")

        mgr = ConfigManager(config_path=fake_config)
        _set_manager(mgr)
        try:
            folders = get_folders()
            assert len(folders) == 2, f"Expected 2 folders, got {len(folders)}: {folders}"
            assert _clean_path(str(d1)) == _clean_path(folders[0])
            assert _clean_path(str(d2)) == _clean_path(folders[1])

            indices = get_search_folder_indices()
            assert 1 in indices, f"Expected 1 in search indices: {indices}"

            config = load_config()
            assert "output_dir" not in config
            assert "search_dirs" not in config
            assert "folders" in config
        finally:
            _set_manager(ConfigManager())
    print("[OK] migrate old config")


@with_temp_config
def test_set_output_reorders(tmpdir):
    """Setting output to a non-zero folder moves it to position 0."""
    d1 = Path(tmpdir) / "a"
    d2 = Path(tmpdir) / "b"
    d3 = Path(tmpdir) / "c"
    d1.mkdir(); d2.mkdir(); d3.mkdir()

    add_folder(str(d1))
    add_folder(str(d2))
    add_folder(str(d3))
    add_search_folder(2)  # c is search

    # Set c (index 2) as output
    set_output_folder(2)

    folders = get_folders()
    assert _clean_path(folders[0]) == _clean_path(str(d3)), "c should be at 0"
    assert get_output_folder_index() == 0

    # Search index should have shifted: c was 2, now 0
    indices = get_search_folder_indices()
    assert 0 in indices, f"Expected 0 in {indices} (c moved to 0)"
    print("[OK] set_output reorders and adjusts search")


if __name__ == "__main__":
    test_empty_config()
    test_add_folders()
    test_add_duplicate()
    test_remove_folder()
    test_output_always_index_zero()
    test_search_folders_independent()
    test_remove_search_folder()
    test_clear_search_folders()
    test_remove_folder_adjusts_search()
    test_expand_dots_basic()
    test_expand_dots_with_subpath()
    test_expand_dots_negative()
    test_expand_dots_unresolved()
    test_mru_depth()
    test_mru_dedup()
    test_clean_path()
    test_resolve_path_value_expands_dots()
    test_migrate_old_config()
    test_set_output_reorders()
    print(f"\n=== All {19} config tests passed ===")
