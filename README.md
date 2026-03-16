# notepad-cleanup

[![PyPI](https://img.shields.io/pypi/v/notepad-cleanup?color=green)](https://pypi.org/project/notepad-cleanup/)
[![Release Date](https://img.shields.io/github/release-date/DazzleTools/notepad-cleanup?color=green)](https://github.com/DazzleTools/notepad-cleanup/releases)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/license-GPL%20v3-green.svg)](https://www.gnu.org/licenses/gpl-3.0.html)
[![Installs](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/djdarcy/a165031b15ecf9b6fdac066d0222a591/raw/installs.json)](https://dazzletools.github.io/notepad-cleanup/stats/#installs)
[![GitHub Discussions](https://img.shields.io/github/discussions/DazzleTools/notepad-cleanup)](https://github.com/DazzleTools/notepad-cleanup/discussions)
[![Platform](https://img.shields.io/badge/platform-Windows%2011-lightgrey.svg)](https://github.com/DazzleTools/notepad-cleanup)

Extract and organize text from all open Windows 11 Notepad tabs using AI-powered categorization.

## What It Does

Windows 11 Notepad supports multiple tabs, making it easy to accumulate dozens of text snippets, code fragments, notes, and temporary data across multiple windows. **notepad-cleanup** extracts all that text in one command, deduplicates it against previous sessions, and organizes it into categorized folders using AI.

## Installation

```bash
pip install notepad-cleanup
```

For virtual environments, source installs, and Claude Code CLI setup, see [docs/install.md](docs/install.md).

```bash
notepad-cleanup extract                    # Extract all Notepad tabs
notepad-cleanup compare --last --link auto # Find and link duplicates
notepad-cleanup organize --last            # AI-powered categorization
```

## Features

- **Two-phase extraction** -- Silent `WM_GETTEXT` for loaded tabs, UI Automation for unloaded tabs
- **Cross-session deduplication** -- Compare against historical sessions with exact and [fuzzy matching](docs/fuzzy-matching.md)
- **Filesystem linking** -- Replace duplicates with hardlinks, symlinks, or DazzleLink descriptors
- **AI organization** -- Claude Code CLI categorizes and renames files automatically
- **Configuration system** -- Unified folder registry with [`...` notation](docs/config.md), MRU history, persistent settings
- **Diff integration** -- Auto-generated scripts for Beyond Compare, WinMerge, VS Code, etc.

## Usage

### First-time setup

```bash
notepad-cleanup config add "C:\Users\YourName\Desktop\Notepad Organize"
notepad-cleanup config set search "...1"
notepad-cleanup config set diff_tool bcomp
```

### Daily workflow

```bash
notepad-cleanup extract                    # 1. Extract all tabs
notepad-cleanup compare --last             # 2. Find duplicates
notepad-cleanup diff --last                # 3. Spot-check in diff tool
notepad-cleanup compare --last --link auto # 4. Link duplicates
notepad-cleanup organize --last            # 5. AI categorization
```

After setup, `--last` auto-uses the most recent extraction. No path copy-pasting.

### Commands

| Command | Purpose |
|---------|---------|
| `extract` | Extract text from all open Notepad windows/tabs |
| `compare` | Find duplicates across historical sessions |
| `organize` | AI-powered file categorization via Claude Code CLI |
| `diff` | Launch diff script to spot-check matched pairs |
| `config` | Manage folders, search dirs, diff tool, settings |
| `run` | Extract + organize in one step |

For full parameter documentation, see [docs/parameters.md](docs/parameters.md).

## Documentation

| Doc | Contents |
|-----|----------|
| [Parameters](docs/parameters.md) | Full command reference with all options |
| [Configuration](docs/config.md) | Folder registry, `...` notation, MRU, search dirs |
| [Fuzzy Matching](docs/fuzzy-matching.md) | Threshold formula, derivation, customization |

## Output Structure

```
notepad-cleanup/nc-2026-03-16__08-15-30/
├── manifest.json                  # Extraction metadata
├── window01/
│   ├── tab01.txt                  # Raw extracted files
│   ├── tab02.txt
│   └── tab03.txt
├── window02/
│   └── tab01.txt
├── organized/                     # AI-organized output (after organize step)
│   ├── code-snippets/
│   │   ├── process-data.py
│   │   └── batch-rename.bat
│   ├── personal-notes/
│   │   └── grocery-list.txt
│   └── _summary.md               # Organization summary
├── _compare_results.json          # Dedup comparison cache
├── _compare_diffs.cmd             # Diff script for spot-checking
├── _dedup_links.json              # Link manifest (if --link used)
├── _organize_prompt.md            # AI prompt used
└── _organize_log.txt              # Claude CLI output
```

## How It Works

### Phase 1: Silent Extraction

Uses `WM_GETTEXT` message to read text from `RichEditD2DPT` child windows. This is completely silent and invisible -- no focus changes, no window activation, no disruption to your workflow.

**Limitation:** Only works for tabs that have been loaded (visited) at least once in the current Notepad session. Unloaded tabs have no `RichEditD2DPT` control yet, so they cannot be read silently.

### Phase 2: Tab Switching (Announced)

For unloaded tabs, uses UI Automation (`TabItem.Select()`) to activate each tab, which forces Windows to load the `RichEditD2DPT` control. Once loaded, the same `WM_GETTEXT` method reads the content.

**Warning:** This steals focus and activates Notepad windows. The tool warns you before Phase 2 starts and waits for confirmation. Do not type or click during Phase 2.

### Organization with AI

After extraction, Claude Code CLI:
1. Reads `manifest.json` to understand the collection
2. Reads each extracted file to determine content type
3. Returns a JSON plan with categories and renamed filenames
4. The tool executes the plan locally (copy files to organized folders)

## Requirements

- **Windows 11** (uses Windows 11 Notepad tab features)
- **Python 3.10+**
- **Claude Code CLI** (optional, for organize step)

For detailed installation instructions, see [docs/install.md](docs/install.md).

## Development

```bash
git clone https://github.com/DazzleTools/notepad-cleanup.git
cd notepad-cleanup
python -m venv venv
venv\Scripts\activate
pip install -e .
```

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Like the project?

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/djdarcy)

## License

notepad-cleanup, Copyright (C) 2026 Dustin Darcy. 

This project is licensed under the GNU General Public License v3.0 — see [LICENSE](LICENSE) for full details.
