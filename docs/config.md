# Configuration Reference

notepad-cleanup stores settings in `~/.notepad-cleanup.json`.

## Quick Reference

```bash
notepad-cleanup config show              # Show all settings
notepad-cleanup config show ...          # Resolve a ... reference
notepad-cleanup config add <path>        # Register a folder
notepad-cleanup config remove <ref>      # Remove a folder
notepad-cleanup config set <key> <val>   # Set a value
notepad-cleanup config unset <key>       # Remove a value
```

## Folder Registry

Folders are stored in an ordered list. Each folder gets a `...N` reference:

| Reference | Meaning |
|-----------|---------|
| `...` | Output folder (always index 0). New extractions go here. |
| `...1` | Second registered folder |
| `...2` | Third registered folder |
| `...N` | Nth registered folder |

### Managing Folders

```bash
# Add a folder
config add "C:\Users\Me\Desktop\Notepad Organize"

# Remove by reference or path
config remove ...2
config remove "C:\Users\Me\Desktop\old-folder"

# Change which folder is the output target
# (moves it to position 0, renumbers everything else)
config set output "C:\Users\Me\Desktop\new-output"
config set output ...2
```

### Folder Roles

Each folder can have roles:

- **output**: Receives new extractions. Always `...` (position 0). Only one folder can be output.
- **search**: Scanned for historical sessions during `compare`. Multiple folders can be search dirs.

A folder can be output only, search only, both, or neither (just registered for `...` reference).

```bash
# Add a folder as a search dir
config set search "C:\path"        # auto-adds to registry if needed
config set search ...2             # by reference

# Remove from search (keeps in registry)
config unset search ...2
config unset search                # clear all search dirs
```

## Recent Extractions (MRU)

Each time `extract` runs, the output path is pushed onto a Most Recently Used list:

| Reference | Meaning |
|-----------|---------|
| `...-1` | Most recent extraction (same as `--last`) |
| `...-2` | Second most recent |
| `...-3` | Third most recent |
| `...-N` | Nth most recent |

```bash
# Check what ...-1 points to
config show ...-1

# Manually push a path onto the MRU
config set mru "C:\path\to\extraction"

# Set max MRU depth (default: 10)
config set mru_depth 20

# Clear all recent extractions
config unset last_extracts
```

## Settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `diff_tool` | string | auto-detect | Diff tool executable name (bcomp, WinMergeU, code, vimdiff) |
| `mru_depth` | int | 10 | Maximum number of recent extractions to remember |

```bash
config set diff_tool bcomp
config set mru_depth 20
config unset diff_tool          # revert to auto-detect
```

## ... Notation

The `...` notation works in any path argument across all commands:

```bash
# In compare
notepad-cleanup compare "...-1"                    # most recent extraction
notepad-cleanup compare "...-2"                    # second most recent
notepad-cleanup compare "...1\subfolder"           # relative to folder ...1

# In config
notepad-cleanup config add "...1\archive"          # expands ...1, adds result
notepad-cleanup config set output "...2"           # set folder ...2 as output

# In diff
notepad-cleanup diff "...-1"                       # diff the most recent
```

### Expansion Rules

- `...` always resolves to the **output folder** (index 0)
- `...N` resolves to **folder N** by index
- `...-N` resolves to the **Nth most recent** extraction
- Expansion happens at runtime, never stored in config
- In `config set`, `...` is expanded to a literal path before storing

### Search Behavior with -s and -ss

| Flags | Parent dir | Saved search dirs | Explicit paths |
|-------|-----------|-------------------|---------------|
| (none) | included | included | - |
| `-ss <path>` | included | included | added |
| `-s <path>` | excluded | excluded | only these |
| `-nsp` | excluded | included | - |
| `-s <path> -ss <path2>` | included | included | both added |

The `-s` flag means "I'm being explicit about what to search." The `-ss` flag means "add this AND keep the defaults."

## Config File Format

The raw JSON structure (you shouldn't need to edit this directly):

```json
{
  "folders": [
    "C:\\Users\\Me\\Desktop\\notepad-cleanup",
    "C:\\Users\\Me\\Desktop\\Notepad Organize"
  ],
  "output_folder": 0,
  "search_folders": [1],
  "diff_tool": "bcomp",
  "mru_depth": 10,
  "last_extracts": [
    "C:\\Users\\Me\\Desktop\\notepad-cleanup-2026-03-16",
    "C:\\Users\\Me\\Desktop\\notepad-cleanup-2026-03-15_07-13-30"
  ]
}
```
