---
title: "Pre-organize deduplication: diff new notes against previous sessions and link duplicates"
labels: enhancement, feature
---

## Summary

Before the AI organize step categorizes files into `organized/`, run a deduplication pre-step that diffs new notes against all previous `notepad-cleanup-*` session folders. When a note already exists in a previous session, create a link to it in the correct location instead of copying it again. Only genuinely new notes are passed to the AI for categorization.

## Motivation

Users who run `notepad-cleanup` regularly accumulate many session folders (e.g., `notepad-cleanup-2026-01-01_…`, `notepad-cleanup-2026-02-14_…`). Without deduplication:

- The same note (e.g., a persistent to-do list or reference snippet) gets re-copied into `organized/` on every session, wasting disk space and polluting category folders.
- The AI agent spends time re-categorizing notes it has seen before, increasing cost and latency.
- The `organized/` folder layout grows inconsistently across sessions because the AI may assign the same file to different categories on different runs.

## Proposed Workflow

```
notepad-cleanup extract
    └──> dedup pre-step (NEW)
            ├── Find all previous notepad-cleanup-* session folders
            ├── Hash / diff extracted files against previously organized files
            ├── For each duplicate: create a DazzleLink (symlink / hardlink / .dazzlelink)
            │       pointing to the original in the previous session
            └── Pass only NEW (non-duplicate) files to the AI organize step
notepad-cleanup organize (AI sees only new files + link stubs for context)
```

## Implementation Notes

### Deduplication heuristics (ordered by cost)

1. **Exact hash match** – SHA-256 of file content; instant, no false positives.
2. **Near-duplicate / fuzzy match** – e.g., difflib similarity ≥ 95 %; catches minor edits of the same note.
3. **Filename + size match** – lightweight secondary signal.

### Linking strategy

- **DazzleLink** (`https://github.com/DazzleTools/dazzlelink/`) — create `.dazzlelink` descriptor files (or OS-native symlinks) from the new session into the original file in the old session. This preserves the file graph across sessions and lets any tool follow the provenance chain.
- **DazzlePreserve** (`https://github.com/DazzleTools/preserve/`) — record file movement / copy events so the provenance graph is queryable; useful for auditing which session introduced a given note.

### Folder context for AI

When the AI organize step runs, it should receive:

- The list of **new files** (content to categorize).
- The list of **linked files** (filename + target path only) so the AI can see the existing folder layout and keep its new categories consistent with prior sessions.

This gives the AI an implicit schema of the `organized/` tree without it having to re-read thousands of old files.

## Proposed Changes

- Add `dedup.py` (or `deduplicator.py`) module to `notepad_cleanup/` with:
  - `find_previous_sessions(base_dir)` — locate sibling `notepad-cleanup-*` folders
  - `hash_organized_files(session_dir)` — build a `{sha256: Path}` index of a session's `organized/` tree
  - `find_duplicate(file_path, index)` — return the canonical path if the file matches, else `None`
  - `create_link(src, target, strategy)` — create a DazzleLink / symlink / hardlink
- Add `--dedup / --no-dedup` flag to `organize` and `run` commands in `cli.py` (default: `--dedup` when previous sessions exist)
- Pass `linked_files` context list to `generate_prompt()` in `organizer.py` so the AI sees what already exists
- Update `execute_plan()` in `organizer.py` to write a link instead of copying when the plan entry is flagged as a duplicate
- Update README with a description of the deduplication step and DazzleLink/DazzlePreserve integration

## Tasks

- [ ] Research DazzleLink API / CLI for creating `.dazzlelink` descriptor files programmatically
- [ ] Research DazzlePreserve API for recording file movement events
- [ ] Decide on fuzzy-match threshold (default 95 %?) and make it configurable via `--dedup-threshold`
- [ ] Implement `find_previous_sessions()` and `hash_organized_files()` in new `dedup.py`
- [ ] Implement `find_duplicate()` with exact + optional fuzzy matching
- [ ] Implement `create_link()` supporting symlink, hardlink, and DazzleLink strategies
- [ ] Add `--dedup` / `--no-dedup` flags to `organize` and `run` commands in `cli.py`
- [ ] Update `generate_prompt()` to include linked-file context for the AI
- [ ] Update `execute_plan()` to write links instead of copies for duplicate entries
- [ ] Add unit tests for `dedup.py` (exact match, fuzzy match, no-match cases)
- [ ] Update README with deduplication workflow and DazzleLink/DazzlePreserve setup instructions
