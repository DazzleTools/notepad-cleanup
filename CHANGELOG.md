# Changelog

All notable changes to notepad-cleanup will be documented in this file.

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
