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
from .dedup import (find_session_dirs, build_hash_index, find_duplicates,
                    find_content_files,
                    generate_unified_diff, near_match_threshold,
                    resolve_diff_tool, launch_diff_tool, create_links,
                    write_link_manifest, generate_diff_script,
                    save_compare_results, load_compare_results,
                    LINK_STRATEGIES, CACHE_FILENAME)
from .config import (
    load_config, save_config, config_get, config_set, config_unset,
    get_folders, add_folder, remove_folder, set_output_folder,
    get_output_folder_index, get_search_folder_indices,
    add_search_folder, remove_search_folder, set_search_folders,
    get_output_dir_for_session, get_default_output_dir,
    get_last_extract, set_last_extract, get_mru_list,
    get_search_dirs,
    resolve_folder, resolve_path_value, expand_dots,
    shorten_path, _clean_path, _is_too_broad, _get_config_path,
)

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
      notepad-cleanup extract                        Extract all tabs
      notepad-cleanup compare <folder> -s <dir>      Find duplicates from previous sessions
      notepad-cleanup organize <folder>              AI-powered categorization
      notepad-cleanup run --verbose                  All steps in one command

    Requires Windows 11 with Notepad open. The organize step requires
    Claude Code CLI (https://claude.ai/claude-code).
    """
    pass


def _do_remove_folder(ref):
    """Shared logic for removing a folder by path or ... reference.

    Used by both 'config remove' and 'config unset ...N'.
    """
    if ref.startswith("..."):
        if ref.startswith("...-"):
            console.print(f"  [yellow]Cannot remove MRU entries directly. "
                          f"Use 'config unset last_extracts' to clear all.[/yellow]")
            return
        if ref == "...":
            idx = 0
        else:
            try:
                idx = int(ref[3:])
            except ValueError:
                console.print(f"  [red]Invalid reference: {ref}[/red]")
                return
        folders = get_folders()
        if idx >= len(folders):
            console.print(f"  [red]No folder at {ref}[/red]")
            return
        if idx == 0:
            console.print(f"  [yellow]Cannot remove output folder (...). "
                          f"Use 'config set output ...N' to change output first.[/yellow]")
            return
        path = folders[idx]
        if remove_folder(idx):
            console.print(f"  Removed: {path}")
        else:
            console.print(f"  [red]Failed to remove {ref}[/red]")
    else:
        resolved = resolve_path_value(ref)
        if remove_folder(resolved):
            console.print(f"  Removed: {resolved}")
        else:
            console.print(f"  [yellow]Folder not found: {resolved}[/yellow]")


@main.command("config")
@click.argument("action", type=click.Choice(["show", "add", "remove", "set", "unset"]),
                default="show")
@click.argument("key", required=False, default=None)
@click.argument("value", required=False, default=None)
def config_cmd(action, key, value):
    """View or modify notepad-cleanup settings.

    \b
    Settings are stored in ~/.notepad-cleanup.json.
    Folders are stored in a unified list, referenced as ..., ...1, ...2, etc.
    Recent extractions are stored as ...-1 (most recent), ...-2, etc.

    \b
    FOLDERS (unified registry -- all paths referenced by ... notation):
      config add <path>                      Add a folder to the registry
      config remove <path-or-...ref>         Remove a folder
      config set output <path-or-...ref>     Set which folder is output (becomes ...)
      config set search <path-or-...ref>     Add a folder to the search list
      config unset search <...ref>           Remove from search list
      config unset search                    Clear all search folders

    \b
    SETTINGS (key-value pairs):
      config set diff_tool <name>            Diff tool (bcomp, WinMergeU, code, etc.)
      config set mru_depth <N>               Max recent extractions to remember (default: 10)
      config set mru <path>                  Push a path onto the recent extractions list
      config unset diff_tool                 Remove a setting
      config unset last_extracts             Clear all recent extractions

    \b
    DISPLAY:
      config show                            Show all settings
      config show <...ref>                   Resolve a specific ... reference
        Examples: show ...   show ...1   show ...-1   show ...-2

    \b
    ... NOTATION:
      ...        Output folder (always first in registry)
      ...1 ...2  Other registered folders by index
      ...-1      Most recent extraction (same as --last)
      ...-2      Second most recent extraction
    """

    # --- SHOW ---
    if action == "show":
        folders = get_folders()
        output_idx = get_output_folder_index()

        # Any ... reference: resolve and print just the value
        if key and key.startswith("..."):
            expanded = expand_dots(key)
            if key in expanded or expanded == str(Path(key).resolve()):
                console.print(f"  {key} = (not set)")
            else:
                console.print(f"  {key} = {expanded}")
            return

        show_folders_only = False  # removed filtered view; config show shows all

        if not show_folders_only:
            console.print(f"\n  Config file: {_get_config_path()}\n")

        # Folder list with ... mnemonics and role tags
        # Output is ALWAYS folders[0] = "..."
        search_indices = get_search_folder_indices()

        if folders:
            console.print("  Folders:")
            for i, f in enumerate(folders):
                dots = "..." if i == 0 else f"...{i}"
                roles = []
                if i == 0:
                    roles.append("output")
                if i in search_indices:
                    roles.append("search")
                role_str = f"  \\[{', '.join(roles)}]" if roles else ""
                console.print(f"    {dots:>5}  {shorten_path(f)}{role_str}")
        else:
            default_out = str(Path.home() / "Desktop" / "notepad-cleanup")
            console.print("  Folders: (none configured)")
            console.print(f"    [dim]Default output: {default_out}[/dim]")


        # Show roles with real paths and (aka: ...) references
        console.print()
        if folders:
            console.print(f"  output_dir = {shorten_path(folders[0])} [dim](aka: ...)[/dim]")

            console.print(f"  search_dirs:")
            console.print(f"    [dim].. (parent of extraction, default; excluded by -s or -nsp)[/dim]")
            if search_indices:
                for i in search_indices:
                    if i < len(folders):
                        dots = "..." if i == 0 else f"...{i}"
                        console.print(f"    {shorten_path(folders[i])} [dim](aka: {dots})[/dim]")
            else:
                console.print(f"    [dim](no additional search dirs configured)[/dim]")
        else:
            default_out = Path.home() / "Desktop" / "notepad-cleanup"
            console.print(f"  output_dir = {default_out} [dim](default)[/dim]")
            console.print(f"  search_dirs:")
            console.print(f"    [dim].. (parent of extraction, default; excluded by -s or -nsp)[/dim]")

        # Other settings
        console.print()
        diff_tool = config_get("diff_tool")
        console.print(f"  diff_tool = {diff_tool or '(auto-detect)'}"
                      f"{'  [dim](default)[/dim]' if not diff_tool else ''}")

        mru = get_mru_list()
        if mru:
            console.print(f"  recent extractions:")
            for i, m in enumerate(mru):
                dots = f"...-{i+1}"
                marker = "  [dim](--last)[/dim]" if i == 0 else ""
                console.print(f"    {dots:>6}  {shorten_path(m)}{marker}")
        else:
            console.print(f"  recent extractions = (none)")
        console.print()

    # --- ADD folder ---
    elif action == "add":
        if not key:
            console.print("[red]Usage: notepad-cleanup config add <path>[/red]")
            return

        resolved = resolve_path_value(key)
        if resolved != key:
            console.print(f"  [dim]Expanded: {key} -> {resolved}[/dim]")

        # Validate path exists or offer to create
        resolved_path = Path(resolved)
        if not resolved_path.exists():
            console.print(f"  [yellow]Directory does not exist: {resolved}[/yellow]")
            if click.confirm("  Create it?", default=True):
                try:
                    resolved_path.mkdir(parents=True, exist_ok=True)
                    console.print(f"  Created: {resolved}")
                except OSError as e:
                    console.print(f"  [red]Failed to create: {e}[/red]")
                    return
            else:
                console.print(f"  [dim]Storing anyway (create the directory before use)[/dim]")

        idx = add_folder(resolved)
        folders = get_folders()
        dots = "..." if idx == 0 else f"...{idx}"
        console.print(f"  Added folder [{idx}]: {resolved}")
        console.print(f"  Reference as: {dots}")

    # --- REMOVE folder ---
    elif action == "remove":
        if not key:
            console.print("[red]Usage: notepad-cleanup config remove <path-or-...ref>[/red]")
            return
        _do_remove_folder(key)

    # --- SET key/value ---
    elif action == "set":
        if not key or value is None:
            console.print("[red]Usage: notepad-cleanup config set <key> <value>[/red]")
            return

        if key in ("output_folder", "output_dir", "output"):
            if set_output_folder(value):
                folders = get_folders()
                idx = get_output_folder_index()
                dots = "..." if idx == 0 else f"...{idx}"
                console.print(f"  Output folder = {dots}  ({folders[idx]})")
            else:
                console.print(f"  [red]Invalid folder reference: {value}[/red]")
        elif key in ("search_folders", "search_dirs", "search"):
            if add_search_folder(value):
                folders = get_folders()
                indices = get_search_folder_indices()
                console.print(f"  Search folders:")
                for i in indices:
                    if i < len(folders):
                        dots = "..." if i == 0 else f"...{i}"
                        console.print(f"    {shorten_path(folders[i])} [dim](aka: {dots})[/dim]")
            else:
                console.print(f"  [red]Invalid folder reference: {value}[/red]")
        elif key in ("mru", "last_extract", "last_extracts"):
            resolved = resolve_path_value(value)
            set_last_extract(Path(resolved))
            mru = get_mru_list()
            console.print(f"  Pushed to recent extractions: {shorten_path(resolved)}")
            console.print(f"  MRU depth: {len(mru)}")
        elif key == "mru_depth":
            config_set(key, int(value))
            console.print(f"  mru_depth = {value}")
        else:
            config_set(key, value)
            console.print(f"  {key} = {value}")

    # --- UNSET key ---
    elif action == "unset":
        if not key:
            console.print("[red]Usage: notepad-cleanup config unset <key>[/red]")
            return

        if key in ("search_folders", "search_dirs", "search"):
            if value:
                # Remove specific folder from search list
                if remove_search_folder(value):
                    folders = get_folders()
                    indices = get_search_folder_indices()
                    if indices:
                        console.print(f"  Search folders:")
                        for i in indices:
                            if i < len(folders):
                                dots = "..." if i == 0 else f"...{i}"
                                console.print(f"    {shorten_path(folders[i])} [dim](aka: {dots})[/dim]")
                    else:
                        console.print(f"  Search folders = (none)")
                else:
                    console.print(f"  [yellow]Not in search list: {value}[/yellow]")
            else:
                # Clear all search folders
                from .dedup import set_search_folders
                set_search_folders([])
                console.print(f"  Cleared all search folders")
        elif key in ("output_folder", "output_dir", "output"):
            console.print(f"  [yellow]Cannot unset output folder (... always has an output)[/yellow]")
        elif key.startswith("..."):
            # ... references mean "remove folder" -- call shared logic
            _do_remove_folder(key)
        else:
            config_unset(key)
            console.print(f"  Removed: {key}")


@main.command()
@click.option("--output-dir", "-o", type=click.Path(), default=None,
              help=f"Output directory (default: {shorten_path(get_default_output_dir())}\\nc-TIMESTAMP)")
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
      notepad-cleanup extract                   Extract to default output folder (...)
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

    # Resolve output directory
    if not output_dir:
        output_dir = str(get_output_dir_for_session())
    else:
        # Warn if extracting to a broad location (Desktop root, home dir, etc.)
        resolved_out = Path(_clean_path(output_dir))
        if _is_too_broad(str(resolved_out)):
            console.print(f"  [yellow]Warning: extracting directly to {shorten_path(str(resolved_out))} "
                          f"will create many files in a shared location.[/yellow]")
            console.print(f"  [dim]Consider using a subfolder like "
                          f"{shorten_path(str(resolved_out / 'notepad-cleanup'))}[/dim]")
            if not click.confirm("  Continue?", default=True):
                return None

    # Save to disk
    console.print("[bold]Saving to disk...[/bold]")
    out_path, manifest = save_extraction(windows, merged, output_dir)

    # Always resolve to absolute for MRU storage
    resolved_path = Path(out_path).resolve()
    set_last_extract(resolved_path)

    # Auto-register the output parent as a folder + search dir
    # so compare --last works immediately without manual config.
    # Skip if the parent is too broad (home dir, drive root, etc.)
    from .config import _manager
    _manager.ensure_defaults()
    parent_str = str(resolved_path.parent)
    if _is_too_broad(parent_str):
        console.print(f"  [yellow]Note: output parent ({shorten_path(parent_str)}) "
                      f"is too broad to auto-register as a search dir.[/yellow]")
        console.print(f"  [dim]Use 'config add <path>' to register a more specific folder.[/dim]")
    else:
        existing_folders = get_folders()
        idx = add_folder(parent_str)
        is_new_folder = idx >= len(existing_folders)
        if idx not in get_search_folder_indices():
            add_search_folder(idx)
            if is_new_folder:
                console.print(f"  [dim]Registered {shorten_path(parent_str)} "
                              f"as search dir (aka: ...{idx if idx > 0 else ''})[/dim]")

    console.print(f"\n  [bold green]Saved {total_extracted} tabs ({total_chars:,} chars)[/bold green]")
    console.print(f"  Output: [link={out_path}]{out_path}[/link]")
    console.print(f"  Manifest: {out_path / 'manifest.json'}\n")

    # Hints about next steps
    search_dirs = get_search_dirs()
    console.print("[dim]Next steps:[/dim]")
    if search_dirs:
        console.print(f"[dim]  Compare against previous sessions (using saved search dirs):[/dim]")
        console.print(f"[dim]    notepad-cleanup compare --last[/dim]")
    else:
        console.print(f"[dim]  Compare against previous sessions:[/dim]")
        console.print(f'[dim]    notepad-cleanup compare --last -s <search-dir>[/dim]')
    console.print(f"[dim]  Or organize directly with AI:[/dim]")
    console.print(f"[dim]    notepad-cleanup organize --last[/dim]\n")

    return str(out_path)


@main.command()
@click.argument("folder", type=click.Path(), required=False, default=None)
@click.option("--last", is_flag=True, help="Use the most recent extraction automatically")
@click.option("--backend", type=click.Choice(["claude", "prompt-only"]), default="claude",
              help="AI backend (default: claude CLI)")
@click.option("--dry-run", is_flag=True, help="Show what would be run without executing")
@click.option("--verbose", "-v", is_flag=True, help="Stream Claude CLI output in real time")
def organize(folder, last, backend, dry_run, verbose):
    """Organize extracted files into named categories using AI.

    \b
    Reads the extraction output, sends file metadata to Claude Code CLI,
    receives a JSON plan (category + descriptive filename per tab), then
    copies files into organized/<category>/ folders.

    \b
    Examples:
      notepad-cleanup organize --last                        Use last extraction
      notepad-cleanup organize ~/Desktop/notepad-cleanup-2026-02-14_01-03-59
      notepad-cleanup organize ./output --verbose
      notepad-cleanup organize ./output --backend prompt-only   Save prompt for manual use
    """

    # Resolve folder from argument or --last (expands ... notation)
    folder = resolve_folder(folder, use_last=last)
    if folder is None:
        console.print("[red]No extraction folder specified.[/red]")
        console.print("  Provide a FOLDER argument or use --last.")
        return
    folder = Path(folder)
    if not folder.exists():
        console.print(f"[red]Folder does not exist: {folder}[/red]")
        return

    if last:
        console.print(f"\n  [dim]Using last extraction: {folder}[/dim]")

    manifest_path = folder / "manifest.json"

    if not manifest_path.exists():
        console.print(f"[red]No manifest.json found in {folder}[/red]")
        console.print("Run 'notepad-cleanup extract' first.")
        sys.exit(1)

    console.print("\n[bold]Notepad Cleanup -- Organize[/bold]\n")

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
@click.argument("folder", type=click.Path(), required=False, default=None)
@click.option("--last", is_flag=True, help="Use the most recent extraction automatically")
@click.option("--search", "-s", "search_only", multiple=True, type=click.Path(),
              help="Search only these directories (overrides saved dirs)")
@click.option("--search-add", "-ss", "search_add", multiple=True, type=click.Path(),
              help="Search these directories AND saved dirs (additive)")
@click.option("--fuzzy", "fuzzy_mode", type=str, default="small",
              help="Fuzzy matching: small (default, <50KB), all, none, or size filter "
                   "e.g. 'lte 100KB', 'gt 50KB'. Operators: lt, lte, gt, gte, eq. "
                   "Use 'none' or --no-fuzzy to disable.")
@click.option("--no-fuzzy", "fuzzy_mode", flag_value="none", is_flag=True,
              help="Disable fuzzy matching (exact only, same as --fuzzy none)")
@click.option("--diff", "-d", is_flag=True,
              help="Open near-matches in external diff tool (Beyond Compare, WinMerge, etc.)")
@click.option("--diff-tool", type=str, default=None,
              help="Diff tool executable name (auto-detected if not set)")
@click.option("--no-search-parent", "-nsp", is_flag=True,
              help="Exclude parent of extraction folder from search")
@click.option("--show-threshold", is_flag=True,
              help="Show the heuristic threshold curve and exit")
@click.option("--link", type=click.Choice(["auto", "symlink", "hardlink", "dazzlelink"]),
              default=None,
              help="Create links for exact duplicates (auto|symlink|hardlink|dazzlelink)")
@click.option("--link-near", is_flag=True,
              help="Also link near-matches (default: only exact matches are linked)")
@click.option("--cache/--no-cache", default=True,
              help="Cache hash index for faster repeat scans (default: enabled)")
def compare(folder, last, search_only, search_add, fuzzy_mode, diff, diff_tool,
            no_search_parent, show_threshold, link, link_near, cache):
    """Compare extracted files against previous sessions to find duplicates.

    \b
    Scans historical notepad-cleanup-* folders for files that match
    your new extraction. Shows exact matches and near-duplicates.

    \b
    Use this to review what's new vs. what you've seen before,
    then decide what to organize with AI.

    \b
    Examples:
      notepad-cleanup compare --last                          Use last extraction + saved dirs
      notepad-cleanup compare "...-2"                         Compare a specific past extraction
      notepad-cleanup compare --last --no-fuzzy               Exact matches only
      notepad-cleanup compare --last --link auto              Compare and link duplicates
      notepad-cleanup compare --last -s "C:\\temp\\notepads"  Search only this folder
      notepad-cleanup compare --last -ss "C:\\temp\\notepads" Search this + saved dirs
      notepad-cleanup compare --last --show-threshold         Show heuristic curve
    """

    # Resolve folder from argument or --last (expands ... notation)
    folder = resolve_folder(folder, use_last=last)
    if folder is None:
        console.print("[red]No extraction folder specified.[/red]")
        console.print("  Provide a FOLDER argument or use --last to use the most recent extraction.")
        last_path = get_last_extract()
        if last_path:
            console.print(f"  Last extraction: {last_path}")
        else:
            console.print("  No previous extraction found. Run 'notepad-cleanup extract' first.")
        return
    folder = Path(folder)
    if not folder.exists():
        console.print(f"[red]Folder does not exist: {folder}[/red]")
        return
    if not folder.is_dir():
        console.print(f"[red]Not a directory: {folder}[/red]")
        return

    if show_threshold:
        console.print("\n[bold]Near-match threshold curve[/bold]")
        console.print("  allowed = 1.396 * ln(size)^2 - 6.75 * ln(size) + 10.14\n")
        console.print(f"  {'File Size':>12}  {'Allowed Diff':>14}  {'Percentage':>12}")
        console.print(f"  {'-' * 12}  {'-' * 14}  {'-' * 12}")
        for size in [10, 25, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 50000]:
            allowed = near_match_threshold(size)
            pct = allowed / size * 100
            console.print(f"  {size:>10} ch  {allowed:>12} ch  {pct:>10.1f}%")
        console.print()
        return
    if last:
        console.print(f"\n  [dim]Using last extraction: {folder}[/dim]")

    console.print("\n[bold]Notepad Cleanup -- Compare[/bold]\n")

    # Build search directory list
    # Rules:
    #   -s only      -> ONLY these paths, no parent, no saved (fully explicit)
    #   -ss present  -> saved dirs + parent + all -s and -ss paths
    #   neither      -> saved dirs + parent (default)
    #   -nsp         -> exclude parent from default/-ss modes
    use_saved = bool(search_add) or not search_only
    include_parent = use_saved and not no_search_parent
    dirs_to_search = []

    if include_parent:
        dirs_to_search.append(folder.parent)

    if use_saved:
        for d in get_search_dirs():
            dirs_to_search.append(Path(d))

    # Add all explicit paths from -s and -ss
    for d in search_only:
        dirs_to_search.append(Path(d))
    for d in search_add:
        dirs_to_search.append(Path(d))

    # Deduplicate
    seen = set()
    unique_dirs = []
    for d in dirs_to_search:
        resolved = str(d.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique_dirs.append(d)
    dirs_to_search = unique_dirs

    console.print(f"  Scanning for historical sessions in:")
    for d in dirs_to_search:
        console.print(f"    [dim]{d}[/dim]")

    # Find historical sessions
    with console.status("Finding historical sessions..."):
        sessions = find_session_dirs(dirs_to_search, current_dir=folder)

    if not sessions:
        console.print("\n  [yellow]No historical sessions found.[/yellow]")
        console.print("  This appears to be the first extraction in these directories.")
        console.print("  Nothing to compare against.\n")
        return

    console.print(f"\n  Found [bold]{len(sessions)}[/bold] historical session(s):")
    for s in sessions[:10]:  # Show first 10
        console.print(f"    [dim]{s.name}[/dim]")
    if len(sessions) > 10:
        console.print(f"    [dim]... and {len(sessions) - 10} more[/dim]")

    # Try loading cached compare results first
    cached_result, stale_reason = load_compare_results(
        folder, search_dirs=dirs_to_search, fuzzy_mode=fuzzy_mode)

    if cached_result and not stale_reason:
        console.print(f"\n  [dim]Using cached compare results "
                      f"(from {folder / '_compare_results.json'})[/dim]")
        result = cached_result
    else:
        if stale_reason and stale_reason != "no saved results":
            console.print(f"\n  [dim]Cached results stale: {stale_reason}. Re-comparing...[/dim]")

        # Build hash index
        cache_path = None
        if cache:
            cache_path = folder.parent / CACHE_FILENAME

        console.print()
        with console.status("Hashing historical files..."):
            hash_index = build_hash_index(sessions, cache_path=cache_path)

        total_indexed = sum(len(v) for v in hash_index.values())
        console.print(f"  Indexed [bold]{total_indexed}[/bold] files "
                      f"([bold]{len(hash_index)}[/bold] unique hashes)")

        # Compare
        console.print()
        new_file_count = len(find_content_files(folder))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TextColumn("[dim]{task.fields[status]}[/dim]"),
            console=console,
        ) as progress:
            task = progress.add_task("Comparing...", total=new_file_count, status="")

            def _on_progress(current, total, file_path, stage):
                rel = file_path.relative_to(folder) if folder in file_path.parents else file_path.name
                if stage == "hash":
                    status = f"{rel} [hash]"
                elif stage.startswith("vs:"):
                    status = f"{rel} [{stage}]"
                else:
                    status = f"{rel} [{stage}]"
                progress.update(task, completed=current, status=status)

            result = find_duplicates(folder, hash_index, fuzzy=fuzzy_mode,
                                     progress_callback=_on_progress)
            progress.update(task, completed=new_file_count, status="done")

        # Save results for reuse
        save_compare_results(result, folder, search_dirs=dirs_to_search,
                             fuzzy_mode=fuzzy_mode)
        console.print(f"  [dim]Compare results saved to {folder / '_compare_results.json'}[/dim]")

    # Display results
    console.print()
    stats = result.stats
    console.print("[bold]Results:[/bold]\n")
    console.print(f"  Total files scanned:  {stats['total_scanned']}")
    console.print(f"  [green]New (unique):[/green]        {stats['new_count']}")
    console.print(f"  [yellow]Exact duplicates:[/yellow]   {stats['exact_count']}")
    console.print(f"  [cyan]Near-duplicates:[/cyan]    {stats['near_count']}")
    console.print(f"  [dim]Skipped (empty):[/dim]    {stats['skipped_count']}")

    # Show exact matches
    if result.exact_matches:
        console.print(f"\n[bold yellow]Exact Matches[/bold yellow] ({len(result.exact_matches)}):\n")
        for m in result.exact_matches:
            rel_new = m.new_path.relative_to(folder)
            console.print(f"  [yellow]{rel_new}[/yellow]")
            console.print(f"    = {m.canonical_path}")
            console.print(f"    [dim]Session: {m.session_dir.name}[/dim]")

    # Show near-matches
    if result.near_matches:
        console.print(f"\n[bold cyan]Near-Matches[/bold cyan] ({len(result.near_matches)}):\n")

        # Resolve diff tool once for all matches
        diff_tool_info = None
        if diff:
            diff_tool_info = resolve_diff_tool(diff_tool)
            if diff_tool_info:
                console.print(f"  [dim]Diff tool: {diff_tool_info[0]}[/dim]\n")
            else:
                console.print("  [yellow]No diff tool found. Falling back to inline diff.[/yellow]")
                console.print("  [dim]Set NOTEPAD_CLEANUP_DIFF_TOOL env var or add "
                              "\"diff_tool\" to ~/.notepad-cleanup.json[/dim]\n")

        for m in result.near_matches:
            rel_new = m.new_path.relative_to(folder)
            file_size = max(len(m.new_path.read_text(encoding="utf-8", errors="replace")),
                            1)
            threshold = near_match_threshold(file_size)
            console.print(f"  [cyan]{rel_new}[/cyan] "
                          f"({m.char_diff} chars different, threshold: {threshold})")
            console.print(f"    ~ {m.canonical_path}")
            console.print(f"    [dim]Session: {m.session_dir.name}[/dim]")

            if diff:
                if diff_tool_info:
                    launched = launch_diff_tool(m.canonical_path, m.new_path,
                                               tool=diff_tool_info)
                    if not launched:
                        console.print(f"    [red]Failed to launch {diff_tool_info[0]}[/red]")
                else:
                    # Inline fallback
                    diff_text = generate_unified_diff(m.canonical_path, m.new_path)
                    if diff_text:
                        console.print()
                        for line in diff_text.splitlines():
                            if line.startswith("+") and not line.startswith("+++"):
                                console.print(f"      [green]{line}[/green]")
                            elif line.startswith("-") and not line.startswith("---"):
                                console.print(f"      [red]{line}[/red]")
                            else:
                                console.print(f"      [dim]{line}[/dim]")
                        console.print()

    # Show new files
    if result.new_files:
        console.print(f"\n[bold green]New Files[/bold green] ({len(result.new_files)}):\n")
        for f in result.new_files:
            rel = f.relative_to(folder)
            try:
                size = f.stat().st_size
                console.print(f"  [green]{rel}[/green]  ({size:,} bytes)")
            except OSError:
                console.print(f"  [green]{rel}[/green]")

    # --- Generate diff script ---
    if result.exact_matches or result.near_matches:
        script_path = generate_diff_script(result, folder, diff_tool=diff_tool)
        console.print(f"\n  [dim]Diff script: {script_path}[/dim]")
        console.print(f"  [dim]Run it to spot-check each pair in your diff tool[/dim]")

    # --- Linking phase ---
    if link and (result.exact_matches or (link_near and result.near_matches)):
        matches_to_link = list(result.exact_matches)
        if link_near:
            matches_to_link.extend(result.near_matches)

        exact_ct = len([m for m in matches_to_link if m.match_type == "exact"])
        near_ct = len([m for m in matches_to_link if m.match_type == "near"])
        parts = []
        if exact_ct:
            parts.append(f"{exact_ct} exact")
        if near_ct:
            parts.append(f"{near_ct} near")

        console.print(f"\n[bold]Ready to link {len(matches_to_link)} duplicate(s) "
                      f"({', '.join(parts)}, strategy: {link})[/bold]")
        console.print(f"  Originals are kept as .orig backups.")

        if not click.confirm("\n  Proceed with linking?", default=True):
            console.print("  Skipping linking. You can re-run with --link later.\n")
        else:
            console.print()
            link_results = create_links(matches_to_link, strategy=link, backup=True)

            succeeded = [r for r in link_results if r.success]
            failed = [r for r in link_results if not r.success]

            if succeeded:
                console.print(f"  [green]Linked: {len(succeeded)}[/green]")
                for r in succeeded:
                    rel = r.new_path.relative_to(folder)
                    console.print(f"    {rel} -> {r.link_type} -> {r.canonical_path.name}")

            if failed:
                console.print(f"  [red]Failed: {len(failed)}[/red]")
                for r in failed:
                    rel = r.new_path.relative_to(folder)
                    console.print(f"    {rel}: {r.error}")

            # Write link manifest
            manifest_path = write_link_manifest(link_results, folder)
            console.print(f"\n  Link manifest: {manifest_path}")

    # Hint for next steps
    console.print()
    if result.new_files:
        console.print("[dim]Next: run 'notepad-cleanup organize' to categorize new files with AI[/dim]")
        console.print(f'[dim]  notepad-cleanup organize "{folder}"[/dim]')
    elif link:
        console.print("[dim]All duplicates linked. No new files to organize.[/dim]")
    else:
        console.print("[dim]All files matched previous sessions -- nothing new to organize.[/dim]")
        if result.exact_matches:
            console.print(f"[dim]Tip: use --link auto to create links for the "
                          f"{len(result.exact_matches)} duplicate(s)[/dim]")
    console.print()


@main.command("diff")
@click.argument("folder", type=click.Path(), required=False, default=None)
@click.option("--last", is_flag=True, help="Use the most recent extraction automatically")
def diff_cmd(folder, last):
    """Open the generated diff script to spot-check compare results.

    \b
    After 'compare' runs, it generates a script (_compare_diffs.cmd)
    that opens each matched pair in your diff tool. This command finds
    and runs that script.

    \b
    Examples:
      notepad-cleanup diff --last                    Diff the last extraction
      notepad-cleanup diff ~/Desktop/notepad-cleanup-2026-03-15
    """

    folder = resolve_folder(folder, use_last=last)
    if folder is None:
        console.print("[red]No extraction folder specified.[/red]")
        console.print("  Provide a FOLDER argument or use --last.")
        return
    folder = Path(folder)
    if not folder.exists():
        console.print(f"[red]Folder does not exist: {folder}[/red]")
        return

    if last:
        console.print(f"\n  [dim]Using last extraction: {folder}[/dim]")

    # Look for the diff script
    import sys as _sys
    ext = ".cmd" if _sys.platform == "win32" else ".sh"
    script_path = folder / f"_compare_diffs{ext}"

    if not script_path.exists():
        console.print(f"\n  [yellow]No diff script found in {folder}[/yellow]")
        console.print("  Run 'notepad-cleanup compare' first to generate it.\n")
        return

    console.print(f"\n  Diff script: {script_path}")

    import subprocess
    try:
        if _sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", str(script_path)], cwd=str(folder))
        else:
            subprocess.Popen(["sh", str(script_path)], cwd=str(folder))
        console.print("  Launched diff tool.\n")
    except OSError as e:
        console.print(f"  [red]Failed to launch: {e}[/red]")
        console.print(f"  You can run it manually: {script_path}\n")


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
