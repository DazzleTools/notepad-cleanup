# Installation Guide

## Quick Install

```bash
pip install notepad-cleanup
```

That's it. Run `notepad-cleanup --version` to verify.

## Virtual Environment (recommended)

Isolate notepad-cleanup from your system Python:

```bash
python -m venv venv
venv\Scripts\activate
pip install notepad-cleanup
```

## Install from Source

For development or to get the latest unreleased changes:

```bash
git clone https://github.com/DazzleTools/notepad-cleanup.git
cd notepad-cleanup
python -m venv venv
venv\Scripts\activate
pip install -e .
```

The `-e` (editable) flag means changes to the source take effect immediately.

## Claude Code CLI (optional)

The `organize` step uses Claude Code CLI for AI-powered categorization. Without it, you can still `extract`, `compare`, and `diff`.

```bash
# Install from https://claude.ai/claude-code
# Verify installation
claude --version
```

## Requirements

- **Windows 11** -- Uses Windows 11 Notepad tab features (RichEditD2DPT controls, UIA TabItems)
- **Python 3.10+** -- Tested on 3.10, 3.11, 3.12, 3.13
- **Claude Code CLI** -- Optional, only needed for the `organize` command

## Dependencies

Installed automatically via pip:

| Package | Purpose |
|---------|---------|
| pywinauto | Windows UI Automation for Notepad interaction |
| pywin32 | Windows API access (WM_GETTEXT, window handles) |
| psutil | Process management |
| click | CLI framework |
| rich | Terminal formatting, progress bars |

## Upgrading

```bash
pip install --upgrade notepad-cleanup
```

## Uninstalling

```bash
pip uninstall notepad-cleanup
```

Configuration is stored in `~/.notepad-cleanup.json` and is not removed by pip. Delete it manually if desired.
