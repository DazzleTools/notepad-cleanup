"""CLI entry point for notepad-cleanup."""

import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from . import __version__
from .discovery import find_notepad_windows, get_richedit_children, get_tab_count
from .extractor import extract_phase1, extract_phase2, merge_results
from .saver import save_extraction
from .organizer import (generate_prompt, invoke_claude_cli, save_prompt_to_file,
                         find_claude_cli, parse_plan, execute_plan)

console = Console()

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, "-V", "--version")
def main():
    """Extract and organize text from open Windows 11 Notepad windows.

    \b
    Two-phase extraction:
      Phase 1  Silent read via WM_GETTEXT (no focus changes)
      Phase 2  UIA tab switching for unloaded tabs (steals focus briefly)

    \b
    Typical workflow:
      notepad-cleanup run --verbose        Full extract + AI organize
      notepad-cleanup extract              Extract only
      notepad-cleanup organize <folder>    Organize a previous extraction

    Requires Windows 11 with Notepad open. The organize step requires
    Claude Code CLI (https://claude.ai/claude-code).
    """
    pass


@main.command()
@click.option("--output-dir", "-o", type=click.Path(), default=None,
              help="Output directory (default: Desktop/notepad-cleanup-TIMESTAMP)")
@click.option("--silent-only", is_flag=True,
              help="Only extract loaded tabs (no tab switching, no focus stealing)")
@click.option("--yes", "-y", is_flag=True,
              help="Skip Phase 2 confirmation prompt")
@click.option("--dry-run", is_flag=True,
              help="Show what would be extracted without saving files")
def extract(output_dir, silent_only, yes, dry_run):
    """Extract text from all open Notepad windows and tabs.

    \b
    Finds every open Notepad window, reads all tab content, and saves
    each tab as a separate text file with a manifest.json index.

    \b
    Examples:
      notepad-cleanup extract                   Extract to Desktop
      notepad-cleanup extract -o ./my-backup    Extract to custom folder
      notepad-cleanup extract --silent-only     Skip unloaded tabs (safe, no focus stealing)
      notepad-cleanup extract --dry-run         Preview without saving
      notepad-cleanup extract -y                Auto-confirm Phase 2
    """

    console.print("\n[bold]Notepad Cleanup — Extract[/bold]\n")

    # Find windows
    with console.status("Finding Notepad windows..."):
        windows = find_notepad_windows()

    if not windows:
        console.print("[yellow]No Notepad windows found.[/yellow]")
        sys.exit(0)

    # Count tabs
    total_tabs = 0
    for w in windows:
        total_tabs += get_tab_count(w["hwnd"])

    console.print(f"  Found [bold]{len(windows)}[/bold] Notepad window(s) with ~[bold]{total_tabs}[/bold] tabs\n")

    # Phase 1: Silent extraction
    console.print("[bold green]Phase 1:[/bold green] Silent extraction (no focus changes)...")
    t0 = time.perf_counter()
    phase1 = extract_phase1(windows)
    t1 = time.perf_counter()

    phase1_count = sum(len(tabs) for tabs in phase1.values())
    phase1_chars = sum(sum(len(t[1]) for t in tabs if t[1]) for tabs in phase1.values())

    console.print(f"  Extracted [bold]{phase1_count}[/bold]/{total_tabs} tabs "
                  f"([bold]{phase1_chars:,}[/bold] chars) in {t1-t0:.1f}s\n")

    # Phase 2: Tab switching (if needed)
    remaining = total_tabs - phase1_count
    phase2 = {}

    if remaining > 0 and not silent_only:
        est_time = remaining * 0.15
        console.print(f"[bold yellow]Phase 2:[/bold yellow] {remaining} tabs need tab switching")
        console.print(f"  Estimated time: ~{est_time:.0f}s")
        console.print(f"  [bold red]WARNING: Notepad windows will briefly take focus.[/bold red]")
        console.print(f"  [bold red]Do NOT type or click until Phase 2 completes.[/bold red]\n")

        if not yes:
            if not click.confirm("  Proceed with Phase 2?", default=True):
                console.print("  Skipping Phase 2. Only silently-loaded tabs will be saved.\n")
                remaining = 0

        if remaining > 0:
            t2 = time.perf_counter()
            phase2 = extract_phase2(windows, phase1)
            t3 = time.perf_counter()

            phase2_count = sum(len(tabs) for tabs in phase2.values())
            phase2_chars = sum(sum(len(t[1]) for t in tabs if t[1]) for tabs in phase2.values())

            console.print(f"\n  Extracted [bold]{phase2_count}[/bold] additional tabs "
                          f"([bold]{phase2_chars:,}[/bold] chars) in {t3-t2:.1f}s\n")

    elif remaining > 0 and silent_only:
        console.print(f"  [dim]{remaining} tabs skipped (--silent-only mode)[/dim]\n")

    # Merge results
    merged = merge_results(phase1, phase2)

    total_extracted = sum(len(tabs) for tabs in merged.values())
    total_chars = sum(sum(len(t[1]) for t in tabs if t[1]) for tabs in merged.values())

    if dry_run:
        console.print("[bold]Dry run — no files written[/bold]\n")
        console.print(f"  Would extract [bold]{total_extracted}[/bold] tabs ({total_chars:,} chars)")
        console.print(f"  From [bold]{len(windows)}[/bold] Notepad windows\n")
        for w in windows:
            hwnd = w["hwnd"]
            tabs = merged.get(hwnd, [])
            if tabs:
                title = w.get("title", "Unknown")[:60]
                console.print(f"  [dim]{title}[/dim] — {len(tabs)} tab(s)")
                for _, text, label, _ in tabs:
                    chars = len(text) if text else 0
                    console.print(f"    {label[:50]}  ({chars:,} chars)")
        console.print()
        return None

    # Save to disk
    console.print("[bold]Saving to disk...[/bold]")
    out_path, manifest = save_extraction(windows, merged, output_dir)

    console.print(f"\n  [bold green]Saved {total_extracted} tabs ({total_chars:,} chars)[/bold green]")
    console.print(f"  Output: [link={out_path}]{out_path}[/link]")
    console.print(f"  Manifest: {out_path / 'manifest.json'}\n")

    # Hint about organize step
    console.print("[dim]Next: run 'notepad-cleanup organize' to rename and group files with AI[/dim]")
    console.print(f"[dim]  notepad-cleanup organize \"{out_path}\"[/dim]\n")

    return str(out_path)


@main.command()
@click.argument("folder", type=click.Path(exists=True))
@click.option("--backend", type=click.Choice(["claude", "prompt-only"]), default="claude",
              help="AI backend (default: claude CLI)")
@click.option("--dry-run", is_flag=True, help="Show what would be run without executing")
@click.option("--verbose", "-v", is_flag=True, help="Stream Claude CLI output in real time")
def organize(folder, backend, dry_run, verbose):
    """Organize extracted files into named categories using AI.

    \b
    Reads the extraction output, sends file metadata to Claude Code CLI,
    receives a JSON plan (category + descriptive filename per tab), then
    copies files into organized/<category>/ folders.

    \b
    Examples:
      notepad-cleanup organize ~/Desktop/notepad-cleanup-2026-02-14_01-03-59
      notepad-cleanup organize ./output --verbose
      notepad-cleanup organize ./output --backend prompt-only   Save prompt for manual use
    """

    folder = Path(folder)
    manifest_path = folder / "manifest.json"

    if not manifest_path.exists():
        console.print(f"[red]No manifest.json found in {folder}[/red]")
        console.print("Run 'notepad-cleanup extract' first.")
        sys.exit(1)

    console.print("\n[bold]Notepad Cleanup — Organize[/bold]\n")

    # Generate prompt
    prompt = generate_prompt(manifest_path)

    if backend == "prompt-only" or dry_run:
        prompt_file = save_prompt_to_file(prompt, folder)
        console.print(f"  Prompt saved to: {prompt_file}")
        console.print(f"\n  To run manually:")
        console.print(f'  [dim]claude -p "$(cat {prompt_file})" --allowedTools "Read,Write,Bash(ls *),Bash(mkdir *),Bash(cp *)"[/dim]')
        console.print(f"  [dim](Run from: {folder})[/dim]\n")
        return

    # Check Claude CLI availability
    claude_path = find_claude_cli()
    if not claude_path:
        console.print("[yellow]Claude Code CLI not found.[/yellow]")
        console.print("Saving prompt to file instead.\n")
        prompt_file = save_prompt_to_file(prompt, folder)
        console.print(f"  Prompt saved to: {prompt_file}")
        console.print(f"  Install Claude Code, then run:")
        console.print(f'  [dim]cd "{folder}" && claude -p "$(cat _organize_prompt.md)" --allowedTools "Read,Write,Bash(ls *),Bash(mkdir *),Bash(cp *)"[/dim]\n')
        return

    console.print(f"  Using Claude Code CLI: {claude_path}")
    console.print(f"  Working directory: {folder}")

    # Also save prompt to file for reference
    save_prompt_to_file(prompt, folder)

    # Log file always written for debugging
    log_file = folder / "_organize_log.txt"

    # Step 1: Get the plan from Claude
    if verbose:
        console.print(f"  Log file: {log_file}")
        console.print(f"  Streaming Claude output below...\n")
        console.print("[dim]" + "─" * 60 + "[/dim]")
        success, output = invoke_claude_cli(prompt, folder, verbose=True, log_file=str(log_file))
        console.print("[dim]" + "─" * 60 + "[/dim]\n")
    else:
        console.print(f"  [dim]Tip: use --verbose to see real-time output[/dim]\n")
        with console.status("Claude is analyzing your files..."):
            success, output = invoke_claude_cli(prompt, folder, log_file=str(log_file))

    if not success:
        console.print(f"[red]Claude CLI failed:[/red] {output[:500]}")
        console.print(f"\n  Full log: {log_file}")
        console.print(f"  Prompt saved to: {folder / '_organize_prompt.md'}")
        console.print("  You can run it manually from a separate terminal.\n")
        return

    # Step 2: Parse the JSON plan
    plan = parse_plan(output)
    if not plan:
        console.print("[red]Could not parse organization plan from Claude's output.[/red]")
        console.print(f"  Raw output saved to: {log_file}")
        console.print(f"  First 500 chars: {output[:500]}\n")
        return

    console.print(f"  Claude proposed a plan for [bold]{len(plan)}[/bold] files\n")

    # Step 3: Execute the plan locally
    with console.status("Organizing files..."):
        summary, stats = execute_plan(plan, folder)

    console.print("[bold green]Organization complete![/bold green]\n")
    console.print(f"  Files organized:  {stats['copied']}")
    if stats['errors']:
        console.print(f"  [red]Errors:         {stats['errors']}[/red]")

    organized = folder / "organized"
    console.print(f"\n  Organized files: {organized}")
    console.print(f"  Summary: {organized / '_summary.md'}")
    console.print(f"  Full log: {log_file}\n")


@main.command()
@click.option("--output-dir", "-o", type=click.Path(), default=None,
              help="Output directory")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmations")
@click.option("--backend", type=click.Choice(["claude", "prompt-only"]), default="claude",
              help="AI backend for organization")
@click.option("--verbose", "-v", is_flag=True, help="Stream Claude CLI output in real time")
@click.pass_context
def run(ctx, output_dir, yes, backend, verbose):
    """Extract all Notepad tabs and organize them with AI in one step.

    \b
    This is the default workflow — runs extract followed by organize.
    Output goes to Desktop/notepad-cleanup-TIMESTAMP/ by default.

    \b
    Examples:
      notepad-cleanup run                  Default: extract + organize
      notepad-cleanup run --verbose        See Claude's progress in real time
      notepad-cleanup run -y --verbose     Skip confirmations, stream output
      notepad-cleanup run -o ./backup      Custom output directory
    """
    # Run extract
    ctx.invoke(extract, output_dir=output_dir, silent_only=False, yes=yes)

    # Find the output dir from the extract step
    # (extract prints it but doesn't return in click context easily)
    # Re-derive it
    if output_dir:
        folder = Path(output_dir)
    else:
        # Find most recent notepad-cleanup folder on desktop
        desktop = Path.home() / "Desktop"
        folders = sorted(desktop.glob("notepad-cleanup-*"), reverse=True)
        if not folders:
            console.print("[red]Could not find extraction output.[/red]")
            return
        folder = folders[0]

    console.print()
    ctx.invoke(organize, folder=str(folder), backend=backend, dry_run=False, verbose=verbose)


if __name__ == "__main__":
    main()
