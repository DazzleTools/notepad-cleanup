# notepad-cleanup

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/license-GPL%20v3-green.svg)](https://www.gnu.org/licenses/gpl-3.0.html)
[![GitHub Discussions](https://img.shields.io/github/discussions/DazzleTools/notepad-cleanup)](https://github.com/DazzleTools/notepad-cleanup/discussions)
[![Platform](https://img.shields.io/badge/platform-Windows%2011-lightgrey.svg)](https://github.com/DazzleTools/notepad-cleanup)

Extract and organize text from all open Windows 11 Notepad tabs using AI-powered categorization.

## What It Does

Windows 11 Notepad supports multiple tabs, making it easy to accumulate dozens of text snippets, code fragments, notes, and temporary data across multiple windows. **notepad-cleanup** extracts all that text in one command and organizes it into categorized folders using Claude Code CLI.

**Two-phase extraction:**
- **Phase 1 (silent):** Extracts loaded tabs via `WM_GETTEXT` without stealing focus
- **Phase 2 (announced):** Switches through unloaded tabs using UI Automation to capture everything

**AI organization:**
- Reads extracted files using Claude Code CLI
- Categorizes by content type (code, notes, configs, etc.)
- Renames files descriptively based on actual content
- Creates organized folder structure automatically

## Features

- **Silent extraction** — No focus stealing for already-loaded tabs
- **Two-phase capture** — Gets all tabs including unloaded ones via UIA tab switching
- **AI-powered organization** — Claude Code CLI reads and categorizes your content
- **Deduplication** — Global dedup across all windows prevents redundant extraction
- **CLI interface** — Simple commands: `extract`, `organize`, `run` (both steps)
- **Manifest tracking** — JSON metadata about every extracted file
- **Windows 11 native** — Built for the new Notepad with RichEditD2DPT controls

## Requirements

- **Windows 11** (uses Windows 11 Notepad tab features)
- **Python 3.10+**
- **Claude Code CLI** (optional, for organize step)

## Installation

### Using pip

```bash
pip install notepad-cleanup
```

### Using venv (recommended)

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install
pip install notepad-cleanup

# Or install from source
git clone https://github.com/DazzleTools/notepad-cleanup.git
cd notepad-cleanup
pip install -e .
```

### Claude Code CLI (optional)

The `organize` step requires Claude Code CLI for AI categorization:

```bash
# Install from https://claude.ai/claude-code
# Verify installation
claude --version
```

## Usage

### Extract only

```bash
notepad-cleanup extract
```

This extracts text from all open Notepad windows/tabs to `Desktop\notepad-cleanup-TIMESTAMP\`.

**Options:**
- `--output-dir PATH` — Custom output directory
- `--silent-only` — Skip Phase 2 (no tab switching, only loaded tabs)
- `--dry-run` — Preview what would be extracted without saving files
- `--yes` — Skip Phase 2 confirmation prompt

### Organize with AI

```bash
notepad-cleanup organize "C:\Users\YourName\Desktop\notepad-cleanup-TIMESTAMP"
```

This reads the extracted files using Claude Code CLI and organizes them into categorized folders.

**Options:**
- `--backend claude` — Use Claude Code CLI (default)
- `--backend prompt-only` — Save prompt without running Claude
- `--dry-run` — Show what would be run without executing
- `--verbose` — Stream Claude CLI output in real-time

### Extract and organize (one command)

```bash
notepad-cleanup run
```

Runs both steps automatically. Use `-h` on any command for full help.

**Options:**
- `--output-dir PATH` — Custom output directory
- `--yes` — Skip confirmations
- `--verbose` — Stream Claude output

## How It Works

### Phase 1: Silent Extraction

Uses `WM_GETTEXT` message to read text from `RichEditD2DPT` child windows. This is completely silent and invisible — no focus changes, no window activation, no disruption to your workflow.

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

**Categories might include:**
- `code-snippets` — Python, JavaScript, batch scripts, PowerShell, etc.
- `config-files` — INI, YAML, JSON configs
- `personal-notes` — Short reminders, quick notes
- `project-planning` — Design docs, task lists
- `reference` — Documentation, links, resources
- `misc` — Everything else

## Output Structure

```
notepad-cleanup-2026-02-14__00-15-30/
├── manifest.json                  # Metadata about all extracted files
├── window01/
│   ├── tab01.txt                  # Original extracted files
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
├── _organize_prompt.md           # AI prompt used
└── _organize_log.txt             # Claude CLI output
```

## Development

### Setup

```bash
git clone https://github.com/DazzleTools/notepad-cleanup.git
cd notepad-cleanup
python -m venv venv
venv\Scripts\activate
pip install -e .
```

### Testing

Manual testing recommended (this tool manipulates real Notepad windows):

1. Open multiple Notepad windows with various tabs
2. Include empty tabs, large tabs, code snippets, notes
3. Run `notepad-cleanup extract --verbose`
4. Verify accuracy of extracted content
5. Run `notepad-cleanup organize` on output
6. Check organized folder structure

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/djdarcy)

## License

notepad-cleanup, Copyright (C) 2026 Dustin Darcy. This program is free software: you can redistribute it and/or modify it under the terms of the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0) as published by the Free Software Foundation.

See [LICENSE](LICENSE) for full details.
