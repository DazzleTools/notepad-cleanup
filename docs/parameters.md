# Command Reference

Full parameter documentation for all notepad-cleanup commands. For a quick overview, see the [README](../README.md).

## extract

Extract text from all open Notepad windows and tabs.

```bash
notepad-cleanup extract [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--output-dir PATH` | `-o` | Output directory (default: `...`/nc-TIMESTAMP) |
| `--silent-only` | | Only extract loaded tabs (no focus stealing) |
| `--yes` | `-y` | Skip Phase 2 confirmation prompt |
| `--dry-run` | | Preview what would be extracted without saving |

**Examples:**
```bash
notepad-cleanup extract                   # Extract to default output folder
notepad-cleanup extract -o ./my-backup    # Custom output directory
notepad-cleanup extract --silent-only     # Skip unloaded tabs (safe)
notepad-cleanup extract --dry-run         # Preview without saving
notepad-cleanup extract -y                # Auto-confirm Phase 2
```

**Notes:**
- Phase 1 silently reads loaded tabs via `WM_GETTEXT` (no focus changes)
- Phase 2 switches through unloaded tabs using UI Automation (steals focus briefly)
- After extraction, the output path is saved to the MRU (`...-1`) and the parent folder is auto-registered as a search dir

## compare

Compare extracted files against previous sessions to find duplicates.

```bash
notepad-cleanup compare [OPTIONS] [FOLDER]
```

| Option | Short | Description |
|--------|-------|-------------|
| `FOLDER` | | Path to extraction folder (supports `...` notation) |
| `--last` | | Use the most recent extraction automatically |
| `--search PATH` | `-s` | Search only these directories (overrides saved dirs) |
| `--search-add PATH` | `-ss` | Search these directories AND saved dirs (additive) |
| `--no-search-parent` | `-nsp` | Exclude parent of extraction folder from search |
| `--fuzzy MODE` | | Fuzzy matching mode (see below) |
| `--no-fuzzy` | | Exact matches only |
| `--link STRATEGY` | | Create links for duplicates: `auto`, `symlink`, `hardlink`, `dazzlelink` |
| `--link-near` | | Also link near-matches (default: only exact) |
| `--diff` | `-d` | Open near-matches in external diff tool |
| `--diff-tool NAME` | | Diff tool executable (auto-detected if not set) |
| `--show-threshold` | | Display the fuzzy threshold curve and exit |
| `--cache / --no-cache` | | Hash index caching (default: enabled) |

### Fuzzy matching modes

| Mode | Meaning |
|------|---------|
| `small` | Default. Fuzzy match files <50KB only |
| `all` | Fuzzy match all files (slow for large files) |
| `none` | Exact matches only (same as `--no-fuzzy`) |
| `lte 100KB` | Fuzzy match files up to 100KB |
| `gt 50KB` | Fuzzy match only files larger than 50KB |

Size operators: `lt`, `lte`, `gt`, `gte`, `eq`. Size units: B, KB, MB, GB, TB.

The threshold formula scales with file size -- stricter for small files, more generous for large. See [fuzzy-matching.md](fuzzy-matching.md) for the full derivation.

### Search directory composition

| Flags | Parent dir | Saved search dirs | Explicit paths |
|-------|-----------|-------------------|---------------|
| (none) | included | included | -- |
| `-ss <path>` | included | included | added |
| `-s <path>` | excluded | excluded | only these |
| `-nsp` | excluded | included | -- |
| `-s <path> -ss <path2>` | included | included | both added |

**Examples:**
```bash
notepad-cleanup compare --last                         # Saved dirs + parent
notepad-cleanup compare "...-2"                        # Specific past extraction
notepad-cleanup compare --last --no-fuzzy              # Exact matches only
notepad-cleanup compare --last --link auto             # Compare and link
notepad-cleanup compare --last -s "D:\archive"         # Search only this dir
notepad-cleanup compare --last -ss "D:\archive"        # This + saved dirs
notepad-cleanup compare --last --show-threshold        # Show threshold curve
```

## organize

Organize extracted files into named categories using AI.

```bash
notepad-cleanup organize [OPTIONS] [FOLDER]
```

| Option | Short | Description |
|--------|-------|-------------|
| `FOLDER` | | Path to extraction folder (supports `...` notation) |
| `--last` | | Use the most recent extraction |
| `--backend` | | `claude` (default) or `prompt-only` |
| `--dry-run` | | Show prompt without executing |
| `--verbose` | `-v` | Stream Claude CLI output in real-time |

**Examples:**
```bash
notepad-cleanup organize --last                  # Organize most recent
notepad-cleanup organize --last --verbose        # Stream output
notepad-cleanup organize --last --dry-run        # Preview prompt
notepad-cleanup organize --last --backend prompt-only  # Save prompt only
```

## diff

Open the generated diff script to spot-check compare results.

```bash
notepad-cleanup diff [OPTIONS] [FOLDER]
```

| Option | Short | Description |
|--------|-------|-------------|
| `FOLDER` | | Path to extraction folder (supports `...` notation) |
| `--last` | | Use the most recent extraction |

After `compare` runs, it generates `_compare_diffs.cmd` (Windows) or `_compare_diffs.sh` (Unix) that opens each matched pair in your diff tool. The `diff` command finds and runs that script.

```bash
notepad-cleanup diff --last
```

## config

View or modify settings. See [config.md](config.md) for the full reference.

```bash
notepad-cleanup config [ACTION] [KEY] [VALUE]
```

| Action | Description |
|--------|-------------|
| `show` | Show all settings (default) |
| `show <...ref>` | Resolve a specific `...` reference |
| `add <path>` | Register a folder |
| `remove <ref>` | Remove a folder by path or `...` reference |
| `set <key> <value>` | Set a value |
| `unset <key> [value]` | Remove a value |

### Key settings

| Key | Description |
|-----|-------------|
| `output` | Set which folder receives new extractions |
| `search` | Add a folder to the search list |
| `diff_tool` | Diff tool executable name |
| `mru` | Push a path onto the MRU list |
| `mru_depth` | Max recent extractions (default: 10) |

### ... notation

| Token | Meaning |
|-------|---------|
| `...` | Output folder (always first in registry) |
| `...1`, `...2` | Other registered folders by index |
| `...-1` | Most recent extraction (same as `--last`) |
| `...-2` | Second most recent extraction |

**Examples:**
```bash
notepad-cleanup config show                        # All settings
notepad-cleanup config show ...                    # What ... resolves to
notepad-cleanup config add "C:\path"               # Register a folder
notepad-cleanup config set output "C:\new-output"  # Change output folder
notepad-cleanup config set search "...1"           # Add to search list
notepad-cleanup config set diff_tool bcomp         # Set diff tool
```

## run

Extract all Notepad tabs and organize with AI in one step.

```bash
notepad-cleanup run [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--output-dir PATH` | `-o` | Custom output directory |
| `--yes` | `-y` | Skip confirmations |
| `--backend` | | `claude` (default) or `prompt-only` |
| `--verbose` | `-v` | Stream Claude output |

```bash
notepad-cleanup run                  # Extract + organize
notepad-cleanup run --verbose        # With real-time output
notepad-cleanup run -y --verbose     # Skip confirmations
```
