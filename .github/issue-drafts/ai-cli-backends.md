---
title: "Support additional AI CLI backends (OpenAI Codex CLI, Gemini CLI, etc.)"
labels: enhancement, feature
---

## Summary

Support additional AI CLI backends beyond Claude Code CLI for the organize step, starting with OpenAI's Codex CLI (`codex`). Users should be able to choose their preferred AI tool via `--backend`.

## Context

Currently the `organize` command supports two backends:

- `--backend claude` — Invokes Claude Code CLI (`claude`) in non-interactive mode
- `--backend prompt-only` — Saves the prompt to `_organize_prompt.md` without running any AI

OpenAI has released **Codex CLI** (`codex`), a command-line AI tool with file-read capabilities similar to Claude Code. Other AI CLI tools (Google Gemini CLI, etc.) are also emerging. Supporting multiple backends would:

- Allow users who don't have Claude Code CLI installed (or prefer OpenAI) to still use the organize step
- Reduce hard dependency on a single vendor's CLI
- Make it easier to add future AI CLI tools as they mature

The current backend logic lives in `organizer.py` (`find_claude_cli`, `invoke_claude_cli`) and `cli.py` (`--backend` option on `organize` and `run` commands).

## Proposed Changes

- Add `--backend codex` option to `organize` and `run` commands alongside `claude` and `prompt-only`
- Add `find_codex_cli()` in `organizer.py` to locate the `codex` / `codex.exe` binary
- Add `invoke_codex_cli()` in `organizer.py` mapping prompt and file-read permissions to Codex CLI flags
- Extract a shared `invoke_ai_cli()` abstraction (or a simple dispatch table) to reduce duplication between `invoke_claude_cli` and `invoke_codex_cli`
- Add `--backend auto` as a future-friendly option that tries Claude first, then Codex, then falls back to `prompt-only`
- Update README: add Codex CLI installation instructions alongside Claude Code CLI

## Backend Comparison

| Feature | Claude Code CLI | OpenAI Codex CLI |
|---|---|---|
| Non-interactive flag | `-p "<prompt>"` | TBD — research required |
| Restrict to Read tool | `--allowedTools "Read,Grep"` | TBD |
| Output format | `--output-format text` | TBD |
| Install URL | https://claude.ai/claude-code | https://github.com/openai/codex |

## Tasks

- [ ] Research Codex CLI invocation flags for non-interactive/headless mode
- [ ] Research how Codex CLI restricts file access (equivalent of `--allowedTools Read`)
- [ ] Add `find_codex_cli()` to `organizer.py`
- [ ] Add `invoke_codex_cli()` to `organizer.py`
- [ ] Update `--backend` choice in `cli.py` to include `codex` (and optionally `auto`)
- [ ] Add dispatch logic in `organize` command to route to the correct `invoke_*` function
- [ ] Update README with Codex CLI install instructions and `--backend codex` usage example
- [ ] Test `--backend codex` end-to-end with a real extraction output
