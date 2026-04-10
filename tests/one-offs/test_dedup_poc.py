"""POC test for dedup module.

Creates temporary session directories with known content,
then verifies that exact matches, near-matches, and new files
are correctly identified.
"""

import tempfile
from pathlib import Path

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from notepad_cleanup.dedup import (
    normalize_text,
    hash_text,
    hash_file,
    find_session_dirs,
    build_hash_index,
    find_duplicates,
    count_char_diffs,
    generate_unified_diff,
    near_match_threshold,
    create_links,
    write_link_manifest,
)


def make_session(base_dir: Path, name: str, files: dict) -> Path:
    """Create a fake session directory with given files and a manifest.json."""
    session = base_dir / name
    win_dir = session / "window01"
    win_dir.mkdir(parents=True)
    for fname, content in files.items():
        (win_dir / fname).write_text(content, encoding="utf-8")
    # Write a minimal manifest.json (required by session discovery)
    import json as _json
    (session / "manifest.json").write_text(
        _json.dumps({
            "version": "1.0",
            "windows": [],
            "window_count": 0,
            "tab_count": len(files),
            "total_chars": sum(len(c) for c in files.values()),
        }),
        encoding="utf-8",
    )
    return session


def test_normalize():
    """Test text normalization."""
    # Trailing whitespace stripped
    assert normalize_text("hello   \nworld  ") == "hello\nworld"
    # Windows line endings normalized
    assert normalize_text("hello\r\nworld") == "hello\nworld"
    # Trailing empty lines stripped
    assert normalize_text("hello\n\n\n") == "hello"
    print("[OK] normalize_text")


def test_hash_consistency():
    """Same content hashes the same regardless of line endings."""
    h1 = hash_text("hello\r\nworld\r\n")
    h2 = hash_text("hello\nworld\n")
    h3 = hash_text("hello\nworld")
    assert h1 == h2 == h3, f"Hashes differ: {h1} vs {h2} vs {h3}"
    print("[OK] hash_text consistency")


def test_char_diffs():
    """Test character difference counting."""
    assert count_char_diffs("hello world", "hello world") == 0
    assert count_char_diffs("hello world", "hello World") == 1  # one char diff
    diff = count_char_diffs("hello world", "hello beautiful world")
    assert diff > 0, f"Expected positive diff, got {diff}"
    print(f"[OK] count_char_diffs ('hello world' vs 'hello beautiful world' = {diff} chars)")


def test_exact_match():
    """Files with identical content are detected as exact matches."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)

        # Historical session
        old_session = make_session(base, "notepad-cleanup-2026-01-01_00-00-00", {
            "tab01.txt": "my todo list\n- buy milk\n- feed cat\n",
            "tab02.txt": "some python code\nimport os\nprint('hi')\n",
        })

        # New session with one exact match, one new file
        new_session = make_session(base, "notepad-cleanup-2026-03-15_00-00-00", {
            "tab01.txt": "my todo list\n- buy milk\n- feed cat\n",  # exact match
            "tab02.txt": "completely new content here\n",             # new
        })

        sessions = find_session_dirs([base], current_dir=new_session)
        assert len(sessions) == 1, f"Expected 1 session, got {len(sessions)}"

        index = build_hash_index(sessions)
        result = find_duplicates(new_session, index, fuzzy=False)

        assert result.stats["exact_count"] == 1, f"Expected 1 exact, got {result.stats}"
        assert result.stats["new_count"] == 1, f"Expected 1 new, got {result.stats}"
        assert result.exact_matches[0].match_type == "exact"
        assert result.exact_matches[0].char_diff == 0
        print(f"[OK] exact match detection: {result.stats}")


def test_near_match():
    """Files with small differences are detected as near-matches."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)

        # Use a longer file so the threshold is more generous
        # (~200 chars -> threshold ~14)
        old_text = (
            "Project meeting notes from Tuesday\n"
            "---\n"
            "1. Review sprint backlog\n"
            "2. Discuss deployment timeline\n"
            "3. Assign code review tasks\n"
            "4. Plan Friday retrospective\n"
        )
        # Small edit: change one word (< threshold for this size)
        new_text = (
            "Project meeting notes from Wednesday\n"
            "---\n"
            "1. Review sprint backlog\n"
            "2. Discuss deployment timeline\n"
            "3. Assign code review tasks\n"
            "4. Plan Friday retrospective\n"
        )

        old_session = make_session(base, "notepad-cleanup-2026-01-01_00-00-00", {
            "tab01.txt": old_text,
        })
        new_session = make_session(base, "notepad-cleanup-2026-03-15_00-00-00", {
            "tab01.txt": new_text,
        })

        diff = count_char_diffs(old_text, new_text)
        file_size = max(len(old_text), len(new_text))
        allowed = near_match_threshold(file_size)

        sessions = find_session_dirs([base], current_dir=new_session)
        index = build_hash_index(sessions)
        result = find_duplicates(new_session, index, fuzzy=True)

        assert result.stats["near_count"] == 1, (
            f"Expected 1 near (diff={diff}, threshold={allowed} for {file_size} chars), "
            f"got {result.stats}"
        )
        m = result.near_matches[0]
        assert m.match_type == "near"
        assert m.char_diff > 0
        assert m.char_diff <= allowed
        print(f"[OK] near match: {m.char_diff} chars diff, threshold={allowed} for {file_size}-char file")


def test_no_match():
    """Completely different files are marked as new."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)

        old_session = make_session(base, "notepad-cleanup-2026-01-01_00-00-00", {
            "tab01.txt": "old content completely different\n",
        })

        new_session = make_session(base, "notepad-cleanup-2026-03-15_00-00-00", {
            "tab01.txt": "brand new unrelated content about quantum physics\n",
        })

        sessions = find_session_dirs([base], current_dir=new_session)
        index = build_hash_index(sessions)
        result = find_duplicates(new_session, index, fuzzy=True)

        assert result.stats["new_count"] == 1, f"Expected 1 new, got {result.stats}"
        print(f"[OK] no match -> new file: {result.stats}")


def test_empty_skipped():
    """Empty files are skipped."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)

        old_session = make_session(base, "notepad-cleanup-2026-01-01_00-00-00", {
            "tab01.txt": "something\n",
        })

        new_session = make_session(base, "notepad-cleanup-2026-03-15_00-00-00", {
            "tab01.txt": "",         # empty
            "tab02.txt": "   \n\n",  # whitespace only
        })

        sessions = find_session_dirs([base], current_dir=new_session)
        index = build_hash_index(sessions)
        result = find_duplicates(new_session, index, fuzzy=True)

        assert result.stats["skipped_count"] == 2, f"Expected 2 skipped, got {result.stats}"
        print(f"[OK] empty files skipped: {result.stats}")


def test_diff_output():
    """Unified diff is generated for near-matches."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)
        f1 = base / "old.txt"
        f2 = base / "new.txt"
        f1.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
        f2.write_text("line 1\nline 2 modified\nline 3\n", encoding="utf-8")

        diff = generate_unified_diff(f1, f2)
        assert "-line 2" in diff
        assert "+line 2 modified" in diff
        print(f"[OK] unified diff output ({len(diff)} chars)")


def test_multi_session():
    """Dedup works across multiple historical sessions."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)

        make_session(base, "notepad-cleanup-2026-01-01_00-00-00", {
            "tab01.txt": "file from january\n",
        })
        make_session(base, "notepad-cleanup-2026-02-01_00-00-00", {
            "tab01.txt": "file from february\n",
        })

        new_session = make_session(base, "notepad-cleanup-2026-03-15_00-00-00", {
            "tab01.txt": "file from january\n",   # matches session 1
            "tab02.txt": "file from february\n",  # matches session 2
            "tab03.txt": "brand new march file\n",
        })

        sessions = find_session_dirs([base], current_dir=new_session)
        assert len(sessions) == 2
        index = build_hash_index(sessions)
        result = find_duplicates(new_session, index, fuzzy=False)

        assert result.stats["exact_count"] == 2, f"Expected 2 exact, got {result.stats}"
        assert result.stats["new_count"] == 1, f"Expected 1 new, got {result.stats}"
        print(f"[OK] multi-session: {result.stats}")


def test_find_sessions_both_formats():
    """find_session_dirs matches both old and new naming formats."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)

        # Create sessions with both name formats
        old1 = make_session(base, "notepad-cleanup-2026-01-01_00-00-00", {"tab01.txt": "old1\n"})
        old2 = make_session(base, "notepad-cleanup-2026-02-14", {"tab01.txt": "old2\n"})
        new1 = make_session(base, "nc-2026-03-22__14-09-18", {"tab01.txt": "new1\n"})
        new2 = make_session(base, "nc-2026-03-22__14-10-08", {"tab01.txt": "new2\n"})

        sessions = find_session_dirs([base])
        names = {s.name for s in sessions}
        assert "notepad-cleanup-2026-01-01_00-00-00" in names, f"Missing old format 1: {names}"
        assert "notepad-cleanup-2026-02-14" in names, f"Missing old format 2: {names}"
        assert "nc-2026-03-22__14-09-18" in names, f"Missing new format 1: {names}"
        assert "nc-2026-03-22__14-10-08" in names, f"Missing new format 2: {names}"
        assert len(sessions) == 4, f"Expected 4 sessions, got {len(sessions)}"
        print(f"[OK] find_sessions_both_formats: {len(sessions)} sessions")


def test_find_sessions_rejects_false_positives():
    """nc-* folders without manifest.json are NOT treated as sessions."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)

        # Real session with manifest
        real = make_session(base, "nc-2026-03-22__14-09-18", {"tab01.txt": "real\n"})

        # False positive folders (start with nc- but no manifest)
        (base / "nc-backups").mkdir()
        (base / "nc-backups" / "random.txt").write_text("backup data\n", encoding="utf-8")
        (base / "nc-scratch").mkdir()
        (base / "nc-old-stuff").mkdir()

        sessions = find_session_dirs([base])
        names = {s.name for s in sessions}

        assert "nc-2026-03-22__14-09-18" in names, f"Real session missing: {names}"
        assert "nc-backups" not in names, f"False positive accepted: {names}"
        assert "nc-scratch" not in names, f"False positive accepted: {names}"
        assert "nc-old-stuff" not in names, f"False positive accepted: {names}"
        assert len(sessions) == 1, f"Expected 1 session, got {len(sessions)}"
        print(f"[OK] find_sessions_rejects_false_positives: {len(sessions)} session")


def test_cache():
    """Hash cache speeds up repeat scans."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)
        cache_path = base / ".dedup-cache.json"

        old_session = make_session(base, "notepad-cleanup-2026-01-01_00-00-00", {
            "tab01.txt": "cached content\n",
        })

        # First build: creates cache
        index1 = build_hash_index([old_session], cache_path=cache_path)
        assert cache_path.exists(), "Cache file not created"

        # Second build: uses cache
        index2 = build_hash_index([old_session], cache_path=cache_path)
        assert index1 == index2, "Cache produced different results"
        print(f"[OK] hash cache works (cache size: {cache_path.stat().st_size} bytes)")


def test_threshold_curve():
    """Heuristic threshold matches anchor points within 20%."""
    anchors = {10: 2, 25: 3, 50: 5, 200: 15, 1000: 30, 5000: 50, 50000: 100}
    for size, expected in anchors.items():
        actual = near_match_threshold(size)
        error_pct = abs(actual - expected) / expected * 100
        assert error_pct < 20, (
            f"size={size}: expected ~{expected}, got {actual} ({error_pct:.0f}% off)"
        )
    print(f"[OK] threshold curve matches all anchors within 20%")


def test_tiny_file_rejects_large_diff():
    """A 20-char file with 15 char changes should NOT be a near-match."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)

        old_session = make_session(base, "notepad-cleanup-2026-01-01_00-00-00", {
            "tab01.txt": "short original text",  # 19 chars
        })

        new_session = make_session(base, "notepad-cleanup-2026-03-15_00-00-00", {
            "tab01.txt": "XXXXX XXXXXXXX XXXX",  # 19 chars, but completely different
        })

        sessions = find_session_dirs([base], current_dir=new_session)
        index = build_hash_index(sessions)
        result = find_duplicates(new_session, index, fuzzy=True)

        # threshold for ~19 chars is ~2, so 15+ diffs should NOT match
        assert result.stats["near_count"] == 0, (
            f"Expected 0 near matches for vastly different tiny files, got {result.stats}"
        )
        assert result.stats["new_count"] == 1
        print(f"[OK] tiny file with large diff correctly rejected as new")


def test_create_links_hardlink():
    """Hardlink creation replaces new file with link to canonical."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)
        content = "identical content for linking test\n"

        old_session = make_session(base, "notepad-cleanup-2026-01-01_00-00-00", {
            "tab01.txt": content,
        })
        new_session = make_session(base, "notepad-cleanup-2026-03-15_00-00-00", {
            "tab01.txt": content,
        })

        sessions = find_session_dirs([base], current_dir=new_session)
        index = build_hash_index(sessions)
        result = find_duplicates(new_session, index, fuzzy=False)

        assert len(result.exact_matches) == 1

        # Create hardlinks (works on same volume)
        link_results = create_links(result.exact_matches, strategy="hardlink", backup=True)

        assert len(link_results) == 1
        lr = link_results[0]
        assert lr.success, f"Link failed: {lr.error}"
        assert lr.link_type == "hardlink"

        # Verify the link works -- reading the new path returns canonical content
        linked_content = lr.new_path.read_text(encoding="utf-8")
        assert linked_content == content

        # Verify backup exists
        assert lr.backup_path.exists()
        assert lr.backup_path.suffix == ".orig"

        print(f"[OK] hardlink creation: {lr.new_path.name} -> {lr.canonical_path.name}")


def test_create_links_dazzlelink():
    """DazzleLink creates a .dazzlelink JSON descriptor."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)
        content = "content for dazzlelink test\n"

        old_session = make_session(base, "notepad-cleanup-2026-01-01_00-00-00", {
            "tab01.txt": content,
        })
        new_session = make_session(base, "notepad-cleanup-2026-03-15_00-00-00", {
            "tab01.txt": content,
        })

        sessions = find_session_dirs([base], current_dir=new_session)
        index = build_hash_index(sessions)
        result = find_duplicates(new_session, index, fuzzy=False)

        link_results = create_links(result.exact_matches, strategy="dazzlelink", backup=True)

        assert len(link_results) == 1
        lr = link_results[0]
        assert lr.success, f"DazzleLink failed: {lr.error}"

        # Verify .dazzlelink file was created
        dl_path = Path(str(lr.new_path) + ".dazzlelink")
        assert dl_path.exists(), f"Expected {dl_path} to exist"

        import json
        dl_data = json.loads(dl_path.read_text(encoding="utf-8"))
        assert dl_data["schema_version"] == 1
        assert dl_data["context"]["reason"] == "dedup_exact_match"

        print(f"[OK] dazzlelink creation: {dl_path.name}")


def test_link_manifest():
    """Link manifest tracks all link operations."""
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmpdir:
        base = Path(tmpdir)
        content = "manifest test content\n"

        old_session = make_session(base, "notepad-cleanup-2026-01-01_00-00-00", {
            "tab01.txt": content,
        })
        new_session = make_session(base, "notepad-cleanup-2026-03-15_00-00-00", {
            "tab01.txt": content,
        })

        sessions = find_session_dirs([base], current_dir=new_session)
        index = build_hash_index(sessions)
        result = find_duplicates(new_session, index, fuzzy=False)
        link_results = create_links(result.exact_matches, strategy="hardlink", backup=True)

        manifest_path = write_link_manifest(link_results, new_session)
        assert manifest_path.exists()

        import json
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["link_count"] == 1
        assert manifest["error_count"] == 0
        assert len(manifest["links"]) == 1

        print(f"[OK] link manifest written ({manifest_path.name})")


if __name__ == "__main__":
    test_normalize()
    test_hash_consistency()
    test_char_diffs()
    test_threshold_curve()
    test_exact_match()
    test_near_match()
    test_no_match()
    test_empty_skipped()
    test_diff_output()
    test_multi_session()
    test_find_sessions_both_formats()
    test_find_sessions_rejects_false_positives()
    test_cache()
    test_tiny_file_rejects_large_diff()
    test_create_links_hardlink()
    test_create_links_dazzlelink()
    test_link_manifest()
    print("\n=== All tests passed ===")
