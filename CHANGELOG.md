# Changelog

All notable changes to notepad-cleanup will be documented in this file.

## [0.2.1] - 2026-03-16

### Added
- GitHub Traffic Tracker (ghtraf): badge gists, archive gist, traffic-badges
  workflow with CI trigger, stats dashboard at docs/stats/
- PyPI publishing via Trusted Publisher (OIDC): publish.yml workflow triggers
  on GitHub Release, builds and uploads automatically
- pyproject.toml (modern Python packaging metadata, replaces setup.py as primary)
- README badges: PyPI version, Release Date, Installs (via ghtraf endpoint)

### Changed
- setup.py updated with long_description, project_urls, additional classifiers
- README updated with v0.2.0 features, new workflow section, links to docs

## [0.2.0] - 2026-03-16

### Added
- **Deduplication system** (`compare` command): detect exact and near-duplicate files
  across historical extraction sessions before organizing with AI
  - Heuristic fuzzy matching with log-quadratic threshold curve (3.5% fit error
    across anchor points). See `docs/fuzzy-matching.md` for derivation
  - Configurable fuzzy modes: `--fuzzy small` (default, <50KB), `--fuzzy all`,
    `--fuzzy "lte 100KB"`, `--no-fuzzy`
  - Progress bar with per-file and per-candidate detail showing fuzzy pipeline
    stage (`[vs: filename [chk:4]]`)
  - Hash caching for fast repeat scans (mtime + size invalidation)
  - Compare results caching (`_compare_results.json`) with staleness detection
  - Historical session indexing: prefers `organized/` files over raw `window*/`
    when both exist; only indexes known text file extensions
- **Filesystem linking** (`--link` flag on `compare`): replace duplicates with
  hardlinks, symlinks, or DazzleLink JSON descriptors
  - Auto-detect best strategy per platform (`--link auto`)
  - Backup originals as `.orig` before linking
  - Confirmation prompt before modifying files
  - Link manifest (`_dedup_links.json`) tracks all operations
- **Diff script generation**: `compare` auto-generates `_compare_diffs.cmd`
  (Windows) / `_compare_diffs.sh` (Unix) to spot-check each matched pair in
  Beyond Compare, WinMerge, VS Code, or other configured diff tool
- **`diff` command**: find and launch the generated diff script (`diff --last`)
- **Configuration system** (`config` command, `~/.notepad-cleanup.json`):
  - Unified folder registry with `...` notation (`...` = output, `...1`/`...2` =
    other folders, `...-1`/`...-2` = recent extractions MRU)
  - `ConfigManager` class in dedicated `config.py` module
  - `config show`, `config add`, `config remove`, `config set`, `config unset`
  - Folder roles: output and search are independent assignments
  - Persistent diff tool, MRU depth, search dirs
  - `...` expansion in all path arguments (resolved at runtime, never stored)
  - `config show <...ref>` resolves any `...` reference for scripting
  - Windows case-insensitive path comparison (`_paths_equal`)
  - Environment variable expansion (`%USERPROFILE%`, `$HOME`)
  - Stray quote stripping for trailing-backslash shell escaping issues
  - Too-broad path detection (warns on home dir, drive roots)
- **`--last` flag** on `compare`, `organize`, and `diff` commands: auto-uses
  most recent extraction from MRU without copy-pasting paths
- **MRU (Most Recently Used)** extraction history: configurable depth (default
  10), referenced as `...-1`, `...-2`, etc.
- **Search dir composition**: `-s` for explicit-only search, `-ss` for additive
  (includes saved dirs), `-nsp` to exclude parent folder
- **`docs/fuzzy-matching.md`**: threshold formula derivation, customization via
  environment variables, fitting script reference
- **`docs/config.md`**: full configuration reference covering folders, roles,
  MRU, settings, `...` notation, and search behavior
- Path shortening in display (`~\Desktop` instead of `C:\Users\...\Desktop`)

### Changed
- Default output directory: `~/Desktop/notepad-cleanup/nc-TIMESTAMP` (was
  `~/Desktop/notepad-cleanup-TIMESTAMP`). Consolidates extractions into one folder
- Extract now auto-registers output parent as a search dir in folder registry
- Extract hints now show both `compare --last` and `organize --last` as next steps
- Help text updated across all commands to reflect new workflow:
  `extract -> compare -> organize`
- Config functions extracted from `dedup.py` into dedicated `config.py` module

## [0.1.4] - 2026-02-19

### Added
- `--dry-run` flag on `extract` — preview what would be extracted without saving files
- `-h` alias for `--help` on all commands
- `-V` alias for `--version`
- Detailed help text with examples for all commands (`extract`, `organize`, `run`)
- Auto-versioning system (ported from wingather): `_version.py` as canonical version
  source, pre-commit/post-commit hooks auto-stamp branch, build number, date, and
  commit hash into version string
- Version scripts: `scripts/update-version.sh`, `scripts/install-hooks.sh`,
  `scripts/paths.sh`, `scripts/hooks/` (pre-commit, post-commit, pre-push)
- CHANGELOG.md
- GitHub Discussions enabled

### Changed
- `setup.py` reads version from `_version.py` via `get_pip_version()` (PEP 440)
- `__init__.py` imports version from `_version.py` (single source of truth)
- README badges: added Discussions, Platform

### Fixed
- Phase 2 now correctly identifies newly loaded RichEditD2DPT controls by tracking
  handle snapshots before/after each `tab.select()`, instead of blindly reading the
  last handle (which often re-read an already-loaded tab)
- Increased Phase 2 tab switch delay from 0.08s to 0.15s for more reliable control loading

## [0.1.3] - 2026-02-14

### Added
- README with features, installation, usage, and architecture docs
- GPL-3.0 license
- FUNDING.yml (GitHub, Ko-fi, Buy Me A Coffee)
- Issue templates for bug reports and feature requests
- CONTRIBUTING.md with development setup guide

### Changed
- CI workflow switched to Windows runners (lint + build)
- CODEOWNERS updated to @djdarcy
- setup.py: added GPL-3.0 classifier, updated author

## [0.1.2] - 2026-02-14

### Fixed
- Phase 2 duplicate extraction: global dedup across all windows using normalized
  text hashing (line endings + trailing whitespace stripped)
- UIA cross-window bleed: use `app.window(handle=)` instead of `app.top_window()`
  since all Notepad instances share one PID
- Phase 2 reads via WM_GETTEXT (same as Phase 1) instead of UIA
  `Document.window_text()` — eliminates hash mismatch between methods
- Ctrl+C during Claude CLI: use `time.sleep()` + `process.poll()` instead of
  `thread.join()` which swallows KeyboardInterrupt on Windows

### Changed
- Each tab preserved as individual file — removed quick-notes.md compaction
- Output folder renamed from `_reorganized/` to `organized/`

## [0.1.1] - 2026-02-14

### Fixed
- `get_tab_count()` rewritten to use UIA `descendants(control_type="TabItem")`
  instead of NotepadTextBox child count, which only counted loaded tabs and
  prevented Phase 2 from triggering
- Phase 2 tab enumeration: use `descendants()` instead of `children()` chain
  since WinUI TabItems aren't direct children of the Tab control

### Changed
- Organizer switched from inline content embedding to Claude Read tool approach:
  short prompt with `--allowedTools Read,Grep`, Claude reads files from disk
- Removed `build_file_listing()` and stdin piping (no longer needed)
- Added threaded stdout reader for Ctrl+C support during Claude CLI subprocess

## [0.1.0] - 2026-02-14

### Added
- Two-phase extraction: silent WM_GETTEXT (Phase 1) + UIA tab switching (Phase 2)
- CLI with `extract`, `organize`, `run` commands (Click + Rich)
- AI organization via Claude Code CLI: returns JSON plan, Python executes file ops
- Manifest.json tracking for all extracted files
- Spike scripts in `tests/one-offs/` for UIA exploration
