"""Deduplication: compare new extractions against historical sessions.

Scans configured directories for previous notepad-cleanup-* session folders,
hashes all files, and identifies exact matches and near-duplicates so users
can review before running AI organization.
"""

import difflib
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import (
    load_config, save_config, config_get, config_set, config_unset,
    get_folders, add_folder, remove_folder,
    set_output_folder, get_output_folder_index,
    get_search_folder_indices, get_search_dirs,
    add_search_folder, remove_search_folder, set_search_folders,
    get_default_output_dir, get_output_dir_for_session,
    get_last_extract, set_last_extract, get_mru_list,
    expand_dots, resolve_path_value, resolve_folder,
    _get_config_path, _clean_path as _clean_path_str,
)


# --- Configuration defaults ---

DEFAULT_SESSION_PATTERN = "notepad-cleanup-*"
CACHE_FILENAME = ".notepad-cleanup-dedup-cache.json"
FUZZY_BIG_FILE_THRESHOLD = 50_000  # 50KB -- files larger than this skip fuzzy by default

# Near-match threshold curve coefficients.
# Formula: allowed = a * ln(size)^2 + b * ln(size) + c
# Derived from heuristic anchor points:
#   10 chars -> 2 allowed, 25 -> 3, 50 -> 5, 200 -> 15,
#   1000 -> 30, 5000 -> 50, 50000 -> 100
# Average fit error: 3.5% across all anchors.
# See docs/fuzzy-matching.md for derivation and customization.
import os as _os
_THRESH_A = float(_os.environ.get("NOTEPAD_CLEANUP_THRESH_A", "1.396"))
_THRESH_B = float(_os.environ.get("NOTEPAD_CLEANUP_THRESH_B", "-6.75"))
_THRESH_C = float(_os.environ.get("NOTEPAD_CLEANUP_THRESH_C", "10.14"))


# --- Data classes ---

@dataclass
class DedupMatch:
    """A match between a new file and a historical file."""
    new_path: Path              # Path to the newly extracted file
    canonical_path: Path        # Path to the historical file it matches
    match_type: str             # "exact" | "near"
    char_diff: int              # 0 for exact, N for near-match
    session_dir: Path           # Which historical session contains the canonical
    new_hash: str               # SHA-256 of the new file
    canonical_hash: str         # SHA-256 of the canonical file


@dataclass
class DedupResult:
    """Result of comparing new files against historical sessions."""
    new_files: list = field(default_factory=list)        # Paths with no match
    exact_matches: list = field(default_factory=list)    # DedupMatch list
    near_matches: list = field(default_factory=list)     # DedupMatch list
    skipped: list = field(default_factory=list)          # Empty/metadata files
    stats: dict = field(default_factory=dict)


@dataclass
class LinkResult:
    """Result of creating a link for a duplicate file."""
    new_path: Path              # The new file that was replaced
    canonical_path: Path        # The target it now points to
    link_type: str              # "symlink" | "hardlink" | "junction" | "dazzlelink"
    success: bool
    error: str = ""
    backup_path: Path = None    # Where the original new file was moved


# Link strategies in order of preference per platform.
LINK_STRATEGIES = {
    "symlink": "Symbolic link (requires Developer Mode on Windows)",
    "hardlink": "Hard link (same volume only, files only)",
    "dazzlelink": "DazzleLink JSON descriptor (cross-platform, no privileges)",
    "auto": "Auto-detect best available method",
}


# --- Text normalization ---

def normalize_text(text: str) -> str:
    """Normalize text for consistent hashing/comparison.

    Strips trailing whitespace per line, normalizes line endings to \\n,
    strips trailing newlines.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip() for line in lines]
    # Strip trailing empty lines
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def hash_text(text: str) -> str:
    """SHA-256 hash of normalized text."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def hash_file(file_path: Path) -> str:
    """SHA-256 hash of a file's normalized text content."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return hash_text(text)
    except (OSError, UnicodeDecodeError):
        # Fall back to raw binary hash
        return _hash_file_binary(file_path)


def _hash_file_binary(file_path: Path) -> str:
    """SHA-256 hash of raw file bytes (fallback for non-text files)."""
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


# --- Session discovery ---

def find_session_dirs(search_dirs: list, current_dir: Path = None) -> list:
    """Find all notepad-cleanup-* session directories.

    Args:
        search_dirs: Directories to search for session folders
        current_dir: The current session directory to exclude

    Returns:
        List of Path objects sorted by name (newest first)
    """
    sessions = []
    seen = set()

    for search_dir in search_dirs:
        search_dir = Path(search_dir)
        if not search_dir.is_dir():
            continue
        for d in search_dir.glob(DEFAULT_SESSION_PATTERN):
            if not d.is_dir():
                continue
            resolved = d.resolve()
            if resolved in seen:
                continue
            if current_dir and resolved == Path(current_dir).resolve():
                continue
            seen.add(resolved)
            sessions.append(d)

    # Sort newest first (the timestamp is in the folder name)
    sessions.sort(key=lambda p: p.name, reverse=True)
    return sessions


# Text file extensions we care about for comparison
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".xml", ".html", ".htm",
    ".css", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".csv",
    ".sh", ".bash", ".bat", ".cmd", ".ps1", ".psm1",
    ".c", ".cpp", ".h", ".hpp", ".java", ".go", ".rs", ".rb", ".pl",
    ".sql", ".r", ".lua", ".vim", ".gitignore", ".env",
    ".log", ".rst", ".tex", ".org",
}


def _is_content_file(path: Path) -> bool:
    """Check if a file is text content worth comparing.

    Skips metadata files, binary files, and non-text extensions.
    """
    name = path.name.lower()

    # Skip metadata files
    if name.startswith("_") or name == "manifest.json":
        return False
    if name.startswith("."):
        return False

    # If it has an extension, check it's a text type
    ext = path.suffix.lower()
    if ext:
        return ext in _TEXT_EXTENSIONS

    # No extension -- assume text (common for notepad extractions)
    return True


def find_content_files(session_dir: Path, for_indexing: bool = False) -> list:
    """Find content files in a session directory.

    When for_indexing=True (building the hash index from historical sessions):
      - If organized/ exists, use ONLY organized/ files (authoritative)
      - Else if window*/ dirs exist, use those (raw extraction)
      - Else scan everything (unknown structure)

    When for_indexing=False (scanning the current extraction):
      - Scan everything (we need to check all new files)

    Skips metadata files (_info.json, manifest.json, _summary.md, etc.)
    """
    session_dir = Path(session_dir)
    organized_dir = session_dir / "organized"
    has_organized = organized_dir.is_dir()
    has_windows = any(session_dir.glob("window[0-9]*"))

    if for_indexing:
        if has_organized:
            scan_root = organized_dir
        elif has_windows:
            # Scan only window*/ subdirs
            files = []
            for win_dir in sorted(session_dir.glob("window[0-9]*")):
                for f in win_dir.rglob("*"):
                    if f.is_file() and _is_content_file(f):
                        files.append(f)
            return files
        else:
            scan_root = session_dir
    else:
        scan_root = session_dir

    files = []
    for f in scan_root.rglob("*"):
        if not f.is_file():
            continue
        if not _is_content_file(f):
            continue
        files.append(f)

    return files


# --- Hash index ---

def build_hash_index(session_dirs: list, cache_path: Path = None) -> dict:
    """Build {sha256: [path1, path2, ...]} index from historical sessions.

    Args:
        session_dirs: List of session directory Paths to scan
        cache_path: Optional path to store/load hash cache

    Returns:
        Dict mapping sha256 hex strings to lists of file Paths
    """
    cache = _load_cache(cache_path) if cache_path else {}
    index = {}  # {hash: [path, path, ...]}

    for session_dir in session_dirs:
        files = find_content_files(session_dir, for_indexing=True)
        for f in files:
            file_key = str(f)

            # Check cache validity (mtime + size)
            cached = cache.get(file_key)
            if cached:
                try:
                    stat = f.stat()
                    if (abs(stat.st_mtime - cached["mtime"]) < 0.01
                            and stat.st_size == cached["size"]):
                        file_hash = cached["sha256"]
                    else:
                        file_hash = hash_file(f)
                        cache[file_key] = {
                            "sha256": file_hash,
                            "mtime": stat.st_mtime,
                            "size": stat.st_size,
                        }
                except OSError:
                    continue
            else:
                try:
                    stat = f.stat()
                    file_hash = hash_file(f)
                    cache[file_key] = {
                        "sha256": file_hash,
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                    }
                except OSError:
                    continue

            if file_hash:
                index.setdefault(file_hash, []).append(f)

    if cache_path:
        _save_cache(cache, cache_path)

    return index


def _load_cache(cache_path: Path) -> dict:
    """Load hash cache from disk."""
    try:
        if cache_path and cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_cache(cache: dict, cache_path: Path):
    """Save hash cache to disk."""
    try:
        cache_path.write_text(
            json.dumps(cache, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


# --- Comparison ---

def near_match_threshold(file_size: int) -> int:
    """Calculate the max allowed character differences for a given file size.

    Uses a log-quadratic curve fitted to heuristic anchor points:
      10 chars -> 2 allowed (20%)
      50 chars -> 5 allowed (10%)
      200 chars -> ~14 allowed (7%)
      1000 chars -> 30 allowed (3%)
      5000 chars -> ~54 allowed (1%)
      50000 chars -> ~100 allowed (0.2%)

    The curve is: allowed = a * ln(size)^2 + b * ln(size) + c
    This naturally scales -- stricter on tiny files, more generous on
    typical notes, and flattens for large files.
    """
    if file_size <= 1:
        return 1
    ln = math.log(file_size)
    allowed = _THRESH_A * ln * ln + _THRESH_B * ln + _THRESH_C
    return max(1, int(round(allowed)))


def count_char_diffs(text_a: str, text_b: str) -> int:
    """Count character-level differences between two texts.

    Uses difflib.SequenceMatcher to find matching blocks, then counts
    the total characters that don't match.
    """
    a = normalize_text(text_a)
    b = normalize_text(text_b)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    matching_chars = sum(block.size for block in matcher.get_matching_blocks())
    return max(len(a), len(b)) - matching_chars


def _parse_size(size_str: str) -> int:
    """Parse a human-readable size string to bytes.

    Examples: "50KB" -> 50000, "1MB" -> 1000000, "100" -> 100
    """
    size_str = size_str.strip().upper()
    multipliers = {"TB": 1_000_000_000_000, "GB": 1_000_000_000,
                   "MB": 1_000_000, "KB": 1_000, "B": 1,
                   "T": 1_000_000_000_000, "G": 1_000_000_000,
                   "M": 1_000_000, "K": 1_000}
    for suffix, mult in multipliers.items():
        if size_str.endswith(suffix):
            return int(float(size_str[:-len(suffix)]) * mult)
    return int(size_str)


def parse_fuzzy_modes(fuzzy_str: str) -> tuple:
    """Parse a fuzzy mode string into (modes_set, size_op, size_limit).

    Returns (modes, size_op, size_limit) where size_op + size_limit
    define which files get fuzzy matching by size.

    Size operators: lt, lte, gt, gte, eq
    - "lte 100KB" means fuzzy only for files <= 100KB
    - "gt 50KB"   means fuzzy only for files > 50KB

    Examples:
        "none"         -> (set(), None, None)         exact only
        "small"        -> ({"small"}, None, None)      default: fuzzy <50KB
        "all"          -> ({"small","big"}, None, None) fuzzy everything
        "lte 100KB"    -> ({"small","big"}, "lte", 100000)
        "gt 1MB"       -> ({"small","big"}, "gt", 1000000)
        "lte100KB"     -> same, no space required
    """
    if not fuzzy_str or fuzzy_str == "none":
        return (set(), None, None)
    if fuzzy_str == "all":
        return ({"small", "big"}, None, None)

    modes = set()
    size_op = None
    size_limit = None

    # Normalize: join space-separated tokens, split on commas
    parts = fuzzy_str.replace(",", " ").split()

    i = 0
    while i < len(parts):
        part = parts[i].lower()

        # Check for size operator (with or without attached size)
        matched_op = None
        for op in ("lte", "gte", "lt", "gt", "eq"):
            if part == op:
                # Operator alone: next token is the size
                matched_op = op
                if i + 1 < len(parts):
                    size_limit = _parse_size(parts[i + 1])
                    i += 1
                break
            elif part.startswith(op) and len(part) > len(op):
                # Operator + size glued together: "gt100KB"
                matched_op = op
                size_limit = _parse_size(part[len(op):])
                break

        if matched_op:
            size_op = matched_op
            modes.update({"small", "big"})
        elif part in ("small", "big"):
            modes.add(part)
        elif part == "all":
            modes.update({"small", "big"})

        i += 1

    if not modes:
        modes.add("small")

    return (modes, size_op, size_limit)


def find_duplicates(
    new_dir: Path,
    hash_index: dict,
    fuzzy: str = "small",
    progress_callback=None,
) -> DedupResult:
    """Compare each new file against the hash index.

    Args:
        new_dir: Directory containing newly extracted files
        hash_index: {sha256: [path, ...]} from build_hash_index()
        fuzzy: Fuzzy mode string -- "none", "small" (default), "all", or
               comma-separated list like "small,big"
        progress_callback: Optional callable(current, total, file_path, stage) for progress.
            stage is a string: "hash", "fuzzy N/M", or "done"

    Returns:
        DedupResult with categorized files
    """
    if isinstance(fuzzy, str):
        fuzzy_modes, size_op, size_limit = parse_fuzzy_modes(fuzzy)
    elif fuzzy:
        fuzzy_modes, size_op, size_limit = {"small"}, None, None
    else:
        fuzzy_modes, size_op, size_limit = set(), None, None

    do_fuzzy = len(fuzzy_modes) > 0
    do_big = "big" in fuzzy_modes

    result = DedupResult()
    new_files = find_content_files(new_dir)
    total = len(new_files)

    for i, new_file in enumerate(new_files):
        if progress_callback:
            progress_callback(i, total, new_file, "hash")
        try:
            text = new_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            result.skipped.append(new_file)
            continue

        normalized = normalize_text(text)

        # Skip empty/trivial files
        if len(normalized.strip()) == 0:
            result.skipped.append(new_file)
            continue

        new_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        # --- Exact match ---
        if new_hash in hash_index:
            canonical = _pick_canonical(hash_index[new_hash])
            result.exact_matches.append(DedupMatch(
                new_path=new_file,
                canonical_path=canonical,
                match_type="exact",
                char_diff=0,
                session_dir=_get_session_dir(canonical),
                new_hash=new_hash,
                canonical_hash=new_hash,
            ))
            continue

        # --- Fuzzy match (if enabled) ---
        if do_fuzzy:
            # Check file size against fuzzy criteria
            file_len = len(normalized)
            if not _fuzzy_size_ok(file_len, do_big, size_op, size_limit):
                result.new_files.append(new_file)
                continue

            # Inner progress: report fuzzy comparison with candidate + step
            def _fuzzy_progress(j, fuzzy_total, candidate_path, check_step):
                if progress_callback:
                    candidate_name = candidate_path.name if candidate_path else "?"
                    progress_callback(i, total, new_file,
                                      f"vs: {candidate_name} [chk:{check_step}]")

            best_match = _find_near_match(
                normalized, new_hash, new_file, hash_index,
                do_big, size_op, size_limit, _fuzzy_progress,
            )
            if best_match:
                result.near_matches.append(best_match)
                continue

        # --- No match ---
        result.new_files.append(new_file)

    result.stats = {
        "total_scanned": len(new_files),
        "exact_count": len(result.exact_matches),
        "near_count": len(result.near_matches),
        "new_count": len(result.new_files),
        "skipped_count": len(result.skipped),
    }

    return result


def _fuzzy_size_ok(file_len: int, do_big: bool,
                   size_op: str = None, size_limit: int = None) -> bool:
    """Check if a file's size qualifies for fuzzy matching.

    If a size_op is set (e.g., "lte 100KB"), use that.
    Otherwise fall back to the default big-file threshold.
    """
    if size_op and size_limit is not None:
        if size_op == "lt":
            return file_len < size_limit
        elif size_op == "lte":
            return file_len <= size_limit
        elif size_op == "gt":
            return file_len > size_limit
        elif size_op == "gte":
            return file_len >= size_limit
        elif size_op == "eq":
            return file_len == size_limit
    # Default: skip big files unless explicitly opted in
    if file_len > FUZZY_BIG_FILE_THRESHOLD and not do_big:
        return False
    return True


def _find_near_match(
    normalized_text: str,
    new_hash: str,
    new_file: Path,
    hash_index: dict,
    include_big: bool = False,
    size_op: str = None,
    size_limit: int = None,
    inner_progress=None,
) -> Optional[DedupMatch]:
    """Find the closest near-match in the hash index.

    Uses near_match_threshold() to calculate the allowed character
    differences based on file size. Pre-filters by size ratio to
    avoid expensive difflib comparisons.

    The inner_progress callback receives (candidate_index, total, candidate_path, check_step)
    where check_step is the current stage in the fuzzy pipeline:
        1 = read      (reading candidate file)
        2 = ratio     (size ratio pre-filter)
        3 = size      (big-file threshold check)
        4 = char-diff (expensive SequenceMatcher comparison)

    Returns the best match or None.
    """
    new_len = len(normalized_text)
    allowed = near_match_threshold(new_len)
    best_match = None
    best_diff = allowed + 1  # Start above threshold
    fuzzy_total = len(hash_index)

    for j, (canonical_hash, paths) in enumerate(hash_index.items()):
        canonical = paths[0]

        # Step 1: Read candidate
        if inner_progress:
            inner_progress(j, fuzzy_total, canonical, 1)
        try:
            canonical_text = normalize_text(
                canonical.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            continue

        # Step 2: Size ratio pre-filter
        if inner_progress:
            inner_progress(j, fuzzy_total, canonical, 2)
        canon_len = len(canonical_text)
        if canon_len == 0:
            continue
        ratio = max(new_len, canon_len) / max(min(new_len, canon_len), 1)
        if ratio > 2.0:
            continue

        # Step 3: Big-file size threshold
        if inner_progress:
            inner_progress(j, fuzzy_total, canonical, 3)
        if not _fuzzy_size_ok(canon_len, include_big, size_op, size_limit):
            continue

        # Step 4: Character diff (the expensive one)
        if inner_progress:
            inner_progress(j, fuzzy_total, canonical, 4)
        diff = count_char_diffs(normalized_text, canonical_text)

        # Use the heuristic threshold for the larger of the two files
        max_len = max(new_len, canon_len)
        effective_threshold = near_match_threshold(max_len)

        if diff <= effective_threshold and diff < best_diff:
            best_diff = diff
            best_match = DedupMatch(
                new_path=new_file,
                canonical_path=_pick_canonical(paths),
                match_type="near",
                char_diff=diff,
                session_dir=_get_session_dir(canonical),
                new_hash=new_hash,
                canonical_hash=canonical_hash,
            )

    return best_match


def _pick_canonical(paths: list) -> Path:
    """Pick the best canonical file from multiple matches.

    The canonical file is the OLDEST instance -- the original source
    of truth for provenance tracking. Among files of the same age,
    prefers organized/ copies (they have descriptive names and category
    context from a previous AI run).

    Uses file creation time (st_ctime on Windows) as the tiebreaker.
    """
    if len(paths) == 1:
        return paths[0]

    # Sort by creation time (oldest first), then prefer organized/
    def _sort_key(p):
        try:
            ctime = p.stat().st_ctime
        except OSError:
            ctime = float("inf")  # missing files sort last
        is_organized = "organized" in str(p)
        # Lower = better: oldest first, organized before raw
        return (ctime, 0 if is_organized else 1)

    ranked = sorted(paths, key=_sort_key)
    return ranked[0]


def _get_session_dir(file_path: Path) -> Path:
    """Walk up from file to find the notepad-cleanup-* session directory."""
    p = file_path
    while p.parent != p:
        if re.match(r"notepad-cleanup-\d{4}", p.name):
            return p
        p = p.parent
    return file_path.parent


# --- Compare results persistence ---

COMPARE_RESULTS_FILENAME = "_compare_results.json"


def save_compare_results(result, output_dir: Path,
                         search_dirs: list = None,
                         fuzzy_mode: str = "small") -> Path:
    """Save DedupResult to JSON for reuse by diff/link/organize commands.

    Also saves file counts for source and historical dirs so we can detect
    when new files appear and the cached results are stale.
    """
    from datetime import datetime

    def _match_to_dict(m):
        return {
            "new_path": str(m.new_path),
            "canonical_path": str(m.canonical_path),
            "match_type": m.match_type,
            "char_diff": m.char_diff,
            "session_dir": str(m.session_dir),
            "new_hash": m.new_hash,
            "canonical_hash": m.canonical_hash,
        }

    # Count files in source and historical dirs for staleness detection
    source_file_count = len(find_content_files(output_dir))
    historical_file_count = 0
    session_dirs_used = []
    if search_dirs:
        sessions = find_session_dirs(search_dirs, current_dir=output_dir)
        session_dirs_used = [str(s) for s in sessions]
        for s in sessions:
            historical_file_count += len(find_content_files(s, for_indexing=True))

    data = {
        "version": "1.0",
        "created_at": datetime.now().isoformat(),
        "fuzzy_mode": fuzzy_mode,
        "source_dir": str(output_dir),
        "source_file_count": source_file_count,
        "historical_file_count": historical_file_count,
        "session_dirs": session_dirs_used,
        "stats": result.stats,
        "exact_matches": [_match_to_dict(m) for m in result.exact_matches],
        "near_matches": [_match_to_dict(m) for m in result.near_matches],
        "new_files": [str(f) for f in result.new_files],
        "skipped": [str(f) for f in result.skipped],
    }

    path = output_dir / COMPARE_RESULTS_FILENAME
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_compare_results(output_dir: Path, search_dirs: list = None,
                         validate: bool = True,
                         fuzzy_mode: str = "small") -> Optional['DedupResult']:
    """Load saved compare results from a previous run.

    Validation checks (when validate=True):
    1. Spot-check file hashes still match saved results
    2. Check source dir file count hasn't changed (new extraction files)
    3. Check historical dirs file count hasn't changed (new historical files)

    If any check fails, returns None so caller knows to re-run compare.

    Returns (DedupResult, stale_reason) -- stale_reason is None if valid,
    or a string explaining why the cache is stale.
    """
    path = Path(output_dir) / COMPARE_RESULTS_FILENAME
    if not path.exists():
        return None, "no saved results"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, "corrupt results file"

    def _dict_to_match(d):
        return DedupMatch(
            new_path=Path(d["new_path"]),
            canonical_path=Path(d["canonical_path"]),
            match_type=d["match_type"],
            char_diff=d["char_diff"],
            session_dir=Path(d["session_dir"]),
            new_hash=d["new_hash"],
            canonical_hash=d["canonical_hash"],
        )

    matches = [_dict_to_match(m) for m in data.get("exact_matches", [])]
    near = [_dict_to_match(m) for m in data.get("near_matches", [])]

    if validate:
        # Check 0: fuzzy mode -- exact matches stay valid, but near-matches
        # and "new" files may need re-checking with different fuzzy criteria
        saved_fuzzy = data.get("fuzzy_mode", "small")
        if saved_fuzzy != fuzzy_mode:
            return None, (f"fuzzy mode changed: was '{saved_fuzzy}', "
                          f"now '{fuzzy_mode}' "
                          f"(exact matches still valid, re-checking fuzzy)")

        # Check 1: spot-check hashes
        all_matches = matches + near
        to_check = []
        if all_matches:
            to_check.append(all_matches[0])
            if len(all_matches) > 1:
                to_check.append(all_matches[-1])
            if len(all_matches) > 4:
                to_check.append(all_matches[len(all_matches) // 2])

        for m in to_check:
            if not m.new_path.exists():
                return None, f"file missing: {m.new_path.name}"
            current_hash = hash_file(m.new_path)
            if current_hash != m.new_hash:
                return None, f"file changed: {m.new_path.name}"

        # Check 2: verify "new" files still exist
        # (If a file we classified as "new" was deleted, results are stale)
        new_files = [Path(f) for f in data.get("new_files", [])]
        for nf in new_files[:3]:  # Spot-check first few
            if not nf.exists():
                return None, f"new file missing: {nf.name}"

    result = DedupResult()
    result.exact_matches = matches
    result.near_matches = near
    result.new_files = [Path(f) for f in data.get("new_files", [])]
    result.skipped = [Path(f) for f in data.get("skipped", [])]
    result.stats = data.get("stats", {})
    return result, None


# --- Diff script generation ---

def generate_diff_script(
    result,
    output_dir: Path,
    diff_tool: str = None,
) -> Path:
    """Generate a runnable script that diffs each match pair.

    Creates _compare_diffs.cmd (Windows) or _compare_diffs.sh (Unix)
    that calls the user's diff tool for each exact and near match.
    Users can run the whole script or cherry-pick individual lines.

    Args:
        result: DedupResult from find_duplicates()
        output_dir: Directory to write the script into
        diff_tool: Diff tool command (auto-detected if None)

    Returns: Path to the generated script
    """
    import sys as _sys

    tool_info = resolve_diff_tool(diff_tool)
    tool_cmd = tool_info[1][0] if tool_info else "bcomp"

    is_windows = _sys.platform == "win32"
    ext = ".cmd" if is_windows else ".sh"
    script_path = output_dir / f"_compare_diffs{ext}"

    lines = []
    if is_windows:
        lines.append("@echo off")
        lines.append(f"REM Generated by notepad-cleanup compare")
        lines.append(f"REM Diff tool: {tool_cmd}")
        lines.append(f"REM Total pairs: {len(result.exact_matches) + len(result.near_matches)}")
        lines.append("")
    else:
        lines.append("#!/bin/sh")
        lines.append(f"# Generated by notepad-cleanup compare")
        lines.append(f"# Diff tool: {tool_cmd}")
        lines.append(f"# Total pairs: {len(result.exact_matches) + len(result.near_matches)}")
        lines.append("")

    pair_num = 0

    if result.exact_matches:
        lines.append(f"REM === Exact matches ({len(result.exact_matches)}) ===" if is_windows
                     else f"# === Exact matches ({len(result.exact_matches)}) ===")
        lines.append("")
        for m in result.exact_matches:
            pair_num += 1
            new_rel = m.new_path.name
            canon_rel = m.canonical_path.name
            if is_windows:
                lines.append(f"REM {pair_num}: {new_rel} = {canon_rel} (exact)")
                lines.append(f'"{tool_cmd}" "{m.new_path}" "{m.canonical_path}"')
            else:
                lines.append(f"# {pair_num}: {new_rel} = {canon_rel} (exact)")
                lines.append(f'"{tool_cmd}" "{m.new_path}" "{m.canonical_path}"')
            lines.append("")

    if result.near_matches:
        lines.append(f"REM === Near matches ({len(result.near_matches)}) ===" if is_windows
                     else f"# === Near matches ({len(result.near_matches)}) ===")
        lines.append("")
        for m in result.near_matches:
            pair_num += 1
            new_rel = m.new_path.name
            canon_rel = m.canonical_path.name
            if is_windows:
                lines.append(f"REM {pair_num}: {new_rel} ~ {canon_rel} ({m.char_diff} chars diff)")
                lines.append(f'"{tool_cmd}" "{m.new_path}" "{m.canonical_path}"')
            else:
                lines.append(f"# {pair_num}: {new_rel} ~ {canon_rel} ({m.char_diff} chars diff)")
                lines.append(f'"{tool_cmd}" "{m.new_path}" "{m.canonical_path}"')
            lines.append("")

    if is_windows:
        lines.append("echo.")
        lines.append(f"echo Done - reviewed {pair_num} pair(s)")
        lines.append("pause")
    else:
        lines.append(f'echo "Done - reviewed {pair_num} pair(s)"')

    script_path.write_text("\r\n".join(lines) if is_windows else "\n".join(lines),
                           encoding="utf-8")
    return script_path


# --- Linking ---

def create_links(
    matches: list,
    strategy: str = "auto",
    backup: bool = True,
) -> list:
    """Create filesystem links from new files to their canonical counterparts.

    For each DedupMatch:
    1. Optionally back up the new file (rename to .orig)
    2. Replace the new file with a link to the canonical file
    3. Record the result

    Args:
        matches: List of DedupMatch objects (exact or near)
        strategy: "symlink", "hardlink", "dazzlelink", or "auto"
        backup: If True, rename original to .orig before linking

    Returns:
        List of LinkResult objects
    """
    if strategy == "auto":
        strategy = _detect_best_strategy()

    results = []
    for m in matches:
        result = _create_single_link(m, strategy, backup)
        results.append(result)

    return results


def _detect_best_strategy() -> str:
    """Detect the best linking strategy for the current platform."""
    import os as _os
    import sys as _sys

    if _sys.platform == "win32":
        # Test if symlinks work (requires Developer Mode or admin)
        if _can_create_symlink():
            return "symlink"
        # Hardlinks work on NTFS without special privileges
        return "hardlink"
    else:
        return "symlink"


def _can_create_symlink() -> bool:
    """Test if symlink creation is available on this system."""
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.txt"
            link = Path(tmp) / "link.txt"
            target.write_text("test", encoding="utf-8")
            link.symlink_to(target)
            return True
    except (OSError, NotImplementedError):
        return False


def _create_single_link(match: DedupMatch, strategy: str, backup: bool) -> LinkResult:
    """Create a single link from new_path to canonical_path."""
    import os as _os
    import shutil as _shutil

    new_path = match.new_path
    canonical = match.canonical_path
    backup_path = None

    # Backup the original file
    if backup:
        backup_path = new_path.with_suffix(new_path.suffix + ".orig")
        try:
            _shutil.move(str(new_path), str(backup_path))
        except OSError as e:
            return LinkResult(
                new_path=new_path,
                canonical_path=canonical,
                link_type=strategy,
                success=False,
                error=f"Backup failed: {e}",
            )
    else:
        # Remove the new file to make room for the link
        try:
            new_path.unlink()
        except OSError as e:
            return LinkResult(
                new_path=new_path,
                canonical_path=canonical,
                link_type=strategy,
                success=False,
                error=f"Remove failed: {e}",
            )

    try:
        if strategy == "symlink":
            # Use absolute path for reliability across working directories
            new_path.symlink_to(canonical.resolve())

        elif strategy == "hardlink":
            _os.link(str(canonical.resolve()), str(new_path))

        elif strategy == "dazzlelink":
            _create_dazzlelink_file(new_path, canonical)

        else:
            return LinkResult(
                new_path=new_path,
                canonical_path=canonical,
                link_type=strategy,
                success=False,
                error=f"Unknown strategy: {strategy}",
                backup_path=backup_path,
            )

        return LinkResult(
            new_path=new_path,
            canonical_path=canonical,
            link_type=strategy,
            success=True,
            backup_path=backup_path,
        )

    except OSError as e:
        # Restore backup on failure
        if backup_path and backup_path.exists():
            try:
                _shutil.move(str(backup_path), str(new_path))
            except OSError:
                pass
        return LinkResult(
            new_path=new_path,
            canonical_path=canonical,
            link_type=strategy,
            success=False,
            error=str(e),
            backup_path=backup_path,
        )


def _create_dazzlelink_file(link_path: Path, target_path: Path):
    """Create a .dazzlelink JSON descriptor file.

    This is a cross-platform alternative when native symlinks aren't
    available. The file is a JSON descriptor compatible with the DazzleLink
    tool (https://github.com/DazzleTools/dazzlelink). Default mode is "open"
    so double-clicking opens the target in its native application.
    """
    from datetime import datetime
    import time

    resolved_target = target_path.resolve()
    now = datetime.now()
    now_ts = time.time()

    # Get target file info
    target_exists = resolved_target.exists()
    target_size = 0
    target_ext = resolved_target.suffix
    target_timestamps = {}
    if target_exists:
        try:
            stat = resolved_target.stat()
            target_size = stat.st_size
            target_timestamps = {
                "created": stat.st_ctime,
                "modified": stat.st_mtime,
                "accessed": stat.st_atime,
                "created_iso": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified_iso": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "accessed_iso": datetime.fromtimestamp(stat.st_atime).isoformat(),
            }
        except OSError:
            pass

    dazzlelink_data = {
        "schema_version": 1,
        "created_by": "notepad-cleanup",
        "creation_timestamp": now_ts,
        "creation_date": now.isoformat(),
        "link": {
            "original_path": str(link_path),
            "target_path": str(resolved_target),
            "type": "dazzlelink",
            "relative_path": False,
        },
        "target": {
            "exists": target_exists,
            "type": "file",
            "size": target_size,
            "extension": target_ext,
            "timestamps": target_timestamps,
        },
        "config": {
            "default_mode": "open",
            "platform": _os.name,
        },
        "context": {
            "reason": "dedup_exact_match",
            "source": "notepad-cleanup",
        },
    }

    # Write with .dazzlelink extension appended
    dl_path = Path(str(link_path) + ".dazzlelink")
    dl_path.write_text(
        json.dumps(dazzlelink_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_link_manifest(results: list, output_dir: Path):
    """Write a manifest of all links created during dedup.

    Creates _dedup_links.json in the session directory for tracking.
    """
    entries = []
    for r in results:
        entries.append({
            "new_path": str(r.new_path),
            "canonical_path": str(r.canonical_path),
            "link_type": r.link_type,
            "success": r.success,
            "error": r.error or None,
            "backup_path": str(r.backup_path) if r.backup_path else None,
        })

    manifest = {
        "version": "1.0",
        "created_at": __import__("datetime").datetime.now().isoformat(),
        "link_count": sum(1 for r in results if r.success),
        "error_count": sum(1 for r in results if not r.success),
        "links": entries,
    }

    manifest_path = output_dir / "_dedup_links.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path


LINK_MANIFEST_FILENAME = "_dedup_links.json"


def load_link_manifest(session_dir: Path) -> dict:
    """Load the dedup link manifest from a session directory.

    Returns the parsed manifest dict, or an empty structure if no manifest exists.
    The returned dict always has a "links" key (list of link entries).
    """
    manifest_path = Path(session_dir) / LINK_MANIFEST_FILENAME
    if not manifest_path.exists():
        return {"links": []}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if "links" not in data:
            data["links"] = []
        return data
    except (json.JSONDecodeError, OSError):
        return {"links": []}


def get_linked_paths(session_dir: Path) -> dict:
    """Return a mapping of linked new_path -> canonical_path for successful links.

    Keys are resolved Path objects (the window*/tab*.txt files that were linked).
    Values are resolved Path objects pointing to the canonical (provenance root) file.
    Returns empty dict if no manifest or no successful links.
    """
    manifest = load_link_manifest(session_dir)
    linked = {}
    for entry in manifest.get("links", []):
        if not entry.get("success"):
            continue
        new_path = Path(entry["new_path"]).resolve()
        canonical_path = Path(entry["canonical_path"]).resolve()
        linked[new_path] = canonical_path
    return linked


# --- Diff tools ---

# Known diff tools in preference order (name, command pattern).
# {old} and {new} are replaced with file paths.
# Beyond Compare variants listed first -- BC5 through BC2 cover all versions.
# "bcomp" is BC's lightweight text-compare; "bcompare" opens the full GUI.
_DIFF_TOOLS = [
    ("bcomp", ["bcomp", "{old}", "{new}"]),            # Beyond Compare (text compare)
    ("bcompare", ["bcompare", "{old}", "{new}"]),      # Beyond Compare (full GUI)
    ("BComp", ["BComp", "{old}", "{new}"]),            # Beyond Compare (case variant)
    ("BCompare", ["BCompare", "{old}", "{new}"]),      # Beyond Compare (case variant)
    ("winmerge", ["WinMergeU", "{old}", "{new}"]),     # WinMerge
    ("meld", ["meld", "{old}", "{new}"]),              # Meld (cross-platform)
    ("kdiff3", ["kdiff3", "{old}", "{new}"]),          # KDiff3
    ("code", ["code", "--diff", "{old}", "{new}"]),    # VS Code
    ("vimdiff", ["vimdiff", "{old}", "{new}"]),        # Vim diff
]





def resolve_diff_tool(explicit: str = None) -> Optional[tuple]:
    """Resolve which diff tool to use.

    Priority order (like git diff.tool):
      1. Explicit --diff-tool argument
      2. NOTEPAD_CLEANUP_DIFF_TOOL environment variable
      3. diff_tool setting in ~/.notepad-cleanup.json
      4. Auto-detect from known tools on PATH

    Args:
        explicit: Tool name passed via --diff-tool CLI option

    Returns (name, cmd_pattern) or None if nothing found.
    """
    import os as _os
    import shutil as _shutil

    # 1. Explicit CLI argument
    tool_name = explicit

    # 2. Environment variable
    if not tool_name:
        tool_name = _os.environ.get("NOTEPAD_CLEANUP_DIFF_TOOL")

    # 3. Config file
    if not tool_name:
        config = load_config()
        tool_name = config.get("diff_tool")

    # If we have a name, look it up in known tools or treat as raw executable
    if tool_name:
        # Check known tools by name
        for name, cmd in _DIFF_TOOLS:
            if name == tool_name or cmd[0].lower() == tool_name.lower():
                if _shutil.which(cmd[0]):
                    return (name, cmd)
        # Treat as raw executable: "tool {old} {new}"
        if _shutil.which(tool_name):
            return (tool_name, [tool_name, "{old}", "{new}"])
        return None  # Explicitly configured but not found

    # 4. Auto-detect from known tools
    for name, cmd in _DIFF_TOOLS:
        if _shutil.which(cmd[0]):
            return (name, cmd)
    return None


def launch_diff_tool(file_a: Path, file_b: Path, tool: tuple = None) -> bool:
    """Launch an external diff tool to compare two files.

    Args:
        file_a: The historical (old) file
        file_b: The new file
        tool: (name, cmd_pattern) from resolve_diff_tool(), or auto-detect

    Returns True if launched, False if no tool found.
    """
    import subprocess as _subprocess

    if tool is None:
        tool = resolve_diff_tool()
    if tool is None:
        return False

    name, cmd_pattern = tool
    cmd = [arg.replace("{old}", str(file_a)).replace("{new}", str(file_b))
           for arg in cmd_pattern]

    try:
        _subprocess.Popen(cmd)
        return True
    except (OSError, FileNotFoundError):
        return False


def generate_unified_diff(file_a: Path, file_b: Path, n_context: int = 3) -> str:
    """Generate a unified diff between two files (fallback when no diff tool).

    Used when --show-diff is passed but no external diff tool is available.
    """
    try:
        text_a = normalize_text(
            file_a.read_text(encoding="utf-8", errors="replace")
        ).splitlines(keepends=True)
        text_b = normalize_text(
            file_b.read_text(encoding="utf-8", errors="replace")
        ).splitlines(keepends=True)
    except OSError:
        return "(unable to read files for diff)"

    diff = difflib.unified_diff(
        text_a, text_b,
        fromfile=str(file_a),
        tofile=str(file_b),
        n=n_context,
    )
    return "".join(diff)
