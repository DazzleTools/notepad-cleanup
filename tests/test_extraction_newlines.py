"""Tests for the #17 CRLF-doubling fix.

Extractions prior to the fix wrote every line as \\r\\r\\n: the control
returned \\r\\n text, and a text-mode write translated its \\n into \\r\\n
again. The fix normalizes to internal \\n at the extraction boundary and
serializes an explicit \\r\\n at the write boundary. There is deliberately
NO hashing tolerance for the old corruption (user directive): corrupted
archives are fixed by repairing the files, not by special-case code.

Maps to the 2026-08-19 CRLF-fix DWP acceptance checks:
    AC2 -> test_saver_writes_crlf_never_crcrlf, test_saver_output_matches_notepad_encoding
    AC3 (amended) -> test_normalize_unifies_clean_encodings, test_no_compat_shim_for_prefix_corruption
    AC4 -> test_cache_rejects_unversioned, test_cache_roundtrip
    (chars) -> test_manifest_chars_exclude_cr
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from notepad_cleanup.dedup import (  # noqa: E402
    CACHE_VERSION,
    _load_cache,
    _save_cache,
    hash_text,
    normalize_text,
)
from notepad_cleanup.saver import save_extraction  # noqa: E402


SAMPLE = "line one\nline two\n\nline four after a blank\nlast line"


def _run_saver(tmp_path, text):
    """Drive the real save_extraction path with one window / one tab."""
    windows = [{"hwnd": 101, "title": "test.txt - Notepad",
                "has_unsaved": False}]
    results = {101: [(0, text, "test-label", 999)]}
    out_dir, manifest = save_extraction(windows, results,
                                        output_dir=tmp_path / "out")
    return out_dir / "window01" / "tab01.txt", manifest


# --- AC2: the writer produces \r\n, never \r\r\n ---------------------------

def test_saver_writes_crlf_never_crcrlf(tmp_path):
    filepath, _ = _run_saver(tmp_path, SAMPLE)
    raw = filepath.read_bytes()
    assert b"\r\r\n" not in raw, "CR doubling regression (#17)"
    assert raw.count(b"\r\n") == SAMPLE.count("\n"), (
        "every internal \\n must serialize as exactly one \\r\\n"
    )
    # no stray lone CRs either
    assert raw.count(b"\r") == raw.count(b"\r\n")


def test_saver_output_matches_notepad_encoding(tmp_path):
    """The on-disk bytes equal the reference CRLF encoding of the content --
    i.e. what Windows Notepad itself would save."""
    filepath, _ = _run_saver(tmp_path, SAMPLE)
    assert filepath.read_bytes() == SAMPLE.replace("\n", "\r\n").encode("utf-8")


# --- clean encodings unify; corrupted archives deliberately do NOT ---------

def test_normalize_unifies_clean_encodings():
    """CRLF (Notepad's save) and internal \\n forms of the same content hash
    identically -- new extractions dedup against clean files."""
    clean_crlf = SAMPLE.replace("\n", "\r\n")          # Notepad's own save
    internal = SAMPLE                                   # post-fix extraction
    assert normalize_text(clean_crlf) == normalize_text(internal)
    assert hash_text(clean_crlf) == hash_text(internal)


def test_no_compat_shim_for_prefix_corruption():
    """Pins a deliberate decision (user directive, 2026-08-19): archives
    corrupted by the pre-#17 bug (\\r\\r\\n endings) are NOT special-cased.
    They normalize with phantom blank lines and do not match clean copies.
    The remedy is repairing the archive files, not tolerant hashing."""
    corrupted = SAMPLE.replace("\n", "\r\r\n")          # pre-fix extraction
    assert hash_text(corrupted) != hash_text(SAMPLE)


def test_normalize_preserves_real_blank_lines():
    text = "para one\r\n\r\npara two"
    assert normalize_text(text) == "para one\n\npara two"


# --- AC4: hash cache is version-gated ---------------------------------------

def test_cache_rejects_unversioned(tmp_path):
    """The pre-versioning flat format (and any wrong version) is discarded --
    its hashes were computed under old normalize semantics."""
    p = tmp_path / "cache.json"
    p.write_text(json.dumps(
        {"C:/x/tab01.txt": {"sha256": "deadbeef", "mtime": 1.0, "size": 10}}),
        encoding="utf-8")
    assert _load_cache(p) == {}
    p.write_text(json.dumps({"version": CACHE_VERSION - 1, "files": {"a": {}}}),
                 encoding="utf-8")
    assert _load_cache(p) == {}


def test_cache_roundtrip(tmp_path):
    p = tmp_path / "cache.json"
    files = {"C:/x/tab01.txt": {"sha256": "abc", "mtime": 1.0, "size": 10}}
    _save_cache(files, p)
    assert _load_cache(p) == files
    envelope = json.loads(p.read_text(encoding="utf-8"))
    assert envelope["version"] == CACHE_VERSION


# --- manifest char counts are CR-free ---------------------------------------

def test_manifest_chars_exclude_cr(tmp_path):
    _, manifest = _run_saver(tmp_path, SAMPLE)
    tab = manifest["windows"][0]["tabs"][0]
    assert tab["chars"] == len(SAMPLE)          # internal \n form, no \r
    assert manifest["total_chars"] == len(SAMPLE)
