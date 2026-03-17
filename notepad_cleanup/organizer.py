"""AI-powered organization of extracted Notepad text.

Claude reads the extracted files via its Read tool, returns a JSON plan,
then our code executes the plan locally (copy/rename/group).
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "organize.md"


def load_prompt_template():
    """Load the organization prompt template."""
    return PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def generate_prompt(manifest_path, linked_paths=None):
    """
    Generate the AI organization prompt from a manifest file.

    Claude sees ALL files (including linked duplicates) so it can create
    a consistent category scheme. The linked_paths info is used later by
    execute_plan() to symlink instead of copy.

    Args:
        manifest_path: Path to manifest.json
        linked_paths: dict from get_linked_paths(). Currently unused in prompt
                      generation but reserved for future reference sections.

    Returns: formatted prompt string
    """
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Build reference section showing previous session's category names
    # so Claude can maintain naming consistency (future: pass directory
    # structure from historical sessions for even better consistency)
    reference_section = ""
    skip_section = ""

    if linked_paths:
        reference_lines = []
        for canonical in linked_paths.values():
            cat_info = _extract_canonical_info(canonical)
            reference_lines.append(f"- {cat_info}")
        if reference_lines:
            reference_section = (
                "\n## Previous Session Names (for naming consistency)\n\n"
                "These categories and names were used in previous sessions. "
                "Consider using consistent category names when organizing similar content:\n\n"
                + "\n".join(sorted(set(reference_lines))) + "\n\n"
            )

    template = load_prompt_template()
    return template.format(
        window_count=manifest.get("window_count", 0),
        tab_count=manifest.get("tab_count", 0),
        total_chars=f"{manifest.get('total_chars', 0):,}",
        skip_section=skip_section,
        reference_section=reference_section,
    )


def _relative_to_base(abs_path, base_dir):
    """Convert an absolute path to a relative string from base_dir."""
    try:
        return str(Path(abs_path).relative_to(base_dir)).replace("\\", "/")
    except (ValueError, TypeError):
        return None


def _extract_canonical_info(canonical_path):
    """Extract 'category/filename' from a canonical path in an organized/ tree.

    E.g., .../organized/code-snippets/batch-rename.bat -> code-snippets/batch-rename.bat
    If the path isn't in an organized/ tree, returns the filename only.
    """
    parts = Path(canonical_path).parts
    try:
        org_idx = [p.lower() for p in parts].index("organized")
        return "/".join(parts[org_idx + 1:])
    except (ValueError, IndexError):
        return Path(canonical_path).name


def find_claude_cli():
    """Find the Claude Code CLI executable."""
    candidates = [
        shutil.which("claude"),
        shutil.which("claude.exe"),
        Path.home() / ".local" / "bin" / "claude.exe",
        Path.home() / ".local" / "bin" / "claude",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


def invoke_claude_cli(prompt, working_dir, verbose=False, log_file=None):
    """
    Invoke Claude Code CLI in non-interactive mode with Read tool access.

    Returns: (success, output_text)
    """
    claude_path = find_claude_cli()
    if not claude_path:
        return False, "Claude Code CLI not found. Install from https://claude.ai/claude-code"

    working_dir = Path(working_dir)

    # Save prompt to file for reference / manual use
    prompt_file = working_dir / "_organize_prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")

    cmd = [
        claude_path,
        "--output-format", "text",
        "--allowedTools", "Read,Grep",
        "-p",
        prompt,
    ]

    # Remove CLAUDECODE env var to allow subprocess invocation
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    log_fh = None
    try:
        if log_file:
            log_fh = open(log_file, "w", encoding="utf-8", errors="replace")

        if verbose:
            process = subprocess.Popen(
                cmd,
                cwd=str(working_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            output_lines = []

            # Read stdout in a daemon thread so Ctrl+C isn't blocked
            def _reader():
                for line in process.stdout:
                    output_lines.append(line)
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    if log_fh:
                        log_fh.write(line)
                        log_fh.flush()

            reader = threading.Thread(target=_reader, daemon=True)
            reader.start()

            try:
                # Poll process status with time.sleep() — sleep is reliably
                # interruptible by KeyboardInterrupt on Windows, unlike
                # thread.join() which can swallow the signal.
                while process.poll() is None:
                    time.sleep(0.2)
                # Process exited; drain any remaining stdout
                reader.join(timeout=5)
            except KeyboardInterrupt:
                process.kill()
                process.wait()
                return False, "Cancelled by user (Ctrl+C)"

            output = "".join(output_lines)
            if process.returncode == 0:
                return True, output
            else:
                return False, f"Claude CLI exited with code {process.returncode}\n{output}"
        else:
            result = subprocess.run(
                cmd,
                cwd=str(working_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
            output = result.stdout
            if log_fh:
                log_fh.write(output)
                if result.stderr:
                    log_fh.write("\n--- STDERR ---\n")
                    log_fh.write(result.stderr)
            if result.returncode == 0:
                return True, output
            else:
                return False, f"Claude CLI exited with code {result.returncode}\nstderr: {result.stderr}"
    except subprocess.TimeoutExpired:
        return False, "Claude CLI timed out after 10 minutes"
    except FileNotFoundError:
        return False, f"Claude CLI not found at: {claude_path}"
    except Exception as e:
        return False, f"Error invoking Claude CLI: {e}"
    finally:
        if log_fh:
            log_fh.close()


def parse_plan(raw_output):
    """
    Parse the JSON plan from Claude's output.

    Handles cases where the JSON might be wrapped in markdown fencing.
    Returns: list of dicts or None on failure.
    """
    text = raw_output.strip()

    # Strip markdown code fencing if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        plan = json.loads(text)
        if isinstance(plan, list):
            return plan
        return None
    except json.JSONDecodeError:
        # Try to find JSON array in the output
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None


def _create_organized_link(canonical_path, dest_path, symlink_ok):
    """Create a symlink or hardlink in organized/ pointing to the canonical file.

    Fallback chain: symlink -> hardlink -> dazzlelink -> returns False (caller copies).

    Returns: (success: bool, link_type: str)
    """
    canonical_resolved = Path(canonical_path).resolve()

    # Try symlink first (visible, cross-volume, shows provenance)
    if symlink_ok:
        try:
            dest_path.symlink_to(canonical_resolved)
            return True, "symlink"
        except OSError:
            pass

    # Fall back to hardlink (same volume only, but no privileges needed)
    try:
        os.link(str(canonical_resolved), str(dest_path))
        return True, "hardlink"
    except OSError:
        pass

    # Fall back to dazzlelink (JSON descriptor, always works, cross-platform)
    try:
        from .dedup import _create_dazzlelink_file
        _create_dazzlelink_file(dest_path, canonical_resolved)
        return True, "dazzlelink"
    except (OSError, ImportError):
        pass

    return False, "failed"


def _write_organized_link_manifest(entries, organized_dir):
    """Write manifest tracking which organized/ files are links vs copies.

    This makes the separate-links command reliable -- it reads this manifest
    rather than guessing from filesystem state.
    """
    import datetime
    manifest = {
        "version": "1.0",
        "created_at": datetime.datetime.now().isoformat(),
        "link_count": len(entries),
        "links": entries,
    }
    manifest_path = Path(organized_dir) / "_organized_links.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def execute_plan(plan, base_dir, linked_paths=None):
    """
    Execute the organization plan by copying/renaming files.

    For linked files (found in linked_paths), creates symlinks in organized/
    pointing to the canonical provenance root instead of copying data.
    For non-linked files, copies normally.

    Args:
        plan: list of dicts with source, category, new_name, reason
        base_dir: path to the extraction output directory
        linked_paths: dict from get_linked_paths() mapping resolved source
                      paths to canonical paths. If None, all files are copied.

    Returns: (summary_text, stats_dict)
    """
    base_dir = Path(base_dir)
    organized_dir = base_dir / "organized"
    organized_dir.mkdir(exist_ok=True)

    stats = {"copied": 0, "linked": 0, "errors": 0}
    categories = {}
    details = []
    organized_links = []  # Track which files were linked vs copied

    # Cache symlink capability test (once per run, not per file)
    from .dedup import _can_create_symlink
    symlink_ok = _can_create_symlink()

    for entry in plan:
        source = entry.get("source", "")
        category = entry.get("category", "misc")
        new_name = entry.get("new_name")
        reason = entry.get("reason", "")

        source_path = base_dir / source
        if not source_path.exists():
            stats["errors"] += 1
            details.append(f"  ERROR: {source} not found")
            continue

        # If Claude didn't provide a name, generate one from the source path
        if not new_name:
            new_name = source.replace("/", "_").replace("\\", "_")

        # Create category folder
        cat_dir = organized_dir / category
        cat_dir.mkdir(exist_ok=True)

        dest_path = cat_dir / new_name

        # Check if this file is a dedup link
        source_resolved = source_path.resolve()
        canonical = linked_paths.get(source_resolved) if linked_paths else None

        if canonical is not None and canonical.exists():
            # Linked file -- create symlink/hardlink to canonical provenance root
            ok, link_type = _create_organized_link(
                canonical, dest_path, symlink_ok)
            if ok:
                stats["linked"] += 1
                categories.setdefault(category, []).append(new_name)
                details.append(f"  {source} -> {category}/{new_name} [{link_type}]")
                organized_links.append({
                    "rel_path": f"{category}/{new_name}",
                    "canonical": str(canonical),
                    "link_type": link_type,
                })
            else:
                # Link failed -- fall back to copy
                try:
                    shutil.copy2(str(source_path), str(dest_path))
                    stats["copied"] += 1
                    categories.setdefault(category, []).append(new_name)
                    details.append(f"  {source} -> {category}/{new_name} [copy fallback]")
                except Exception as e:
                    stats["errors"] += 1
                    details.append(f"  ERROR copying {source}: {e}")
        else:
            # Normal file -- copy as before
            try:
                shutil.copy2(str(source_path), str(dest_path))
                stats["copied"] += 1
                categories.setdefault(category, []).append(new_name)
                details.append(f"  {source} -> {category}/{new_name}")
            except Exception as e:
                stats["errors"] += 1
                details.append(f"  ERROR copying {source}: {e}")

    # Write organized link tracking manifest
    if organized_links:
        _write_organized_link_manifest(organized_links, organized_dir)

    # Write summary
    summary_lines = ["# Organization Summary\n"]
    summary_lines.append(f"- **Files copied**: {stats['copied']}")
    if stats.get("linked", 0):
        summary_lines.append(f"- **Files linked**: {stats['linked']} (symlink/hardlink to canonical)")
    summary_lines.append(f"- **Categories**: {len(categories)}")
    if stats["errors"]:
        summary_lines.append(f"- **Errors**: {stats['errors']}")
    summary_lines.append("")

    summary_lines.append("## Categories\n")
    for cat, files in sorted(categories.items()):
        summary_lines.append(f"### {cat} ({len(files)} files)")
        for f in files:
            summary_lines.append(f"- {f}")
        summary_lines.append("")

    summary_lines.append("## File Mapping\n")
    summary_lines.extend(details)

    summary_text = "\n".join(summary_lines)
    summary_path = organized_dir / "_summary.md"
    summary_path.write_text(summary_text, encoding="utf-8")

    return summary_text, stats


def save_prompt_to_file(prompt, output_dir):
    """Save the generated prompt to a file for manual use."""
    output_dir = Path(output_dir)
    prompt_file = output_dir / "_organize_prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    return prompt_file


def separate_links(organized_dir, links_dir_name="organized-links", dry_run=False):
    """Move symlinked/hardlinked files from organized/ into a parallel tree.

    Detects links via _organized_links.json (written by execute_plan) and
    filesystem symlink detection. Moves them to a sibling directory preserving
    relative directory structure.

    Args:
        organized_dir: Path to the organized/ directory
        links_dir_name: Name for the sibling directory (default: "organized-links")

    Returns: (stats_dict, details_list)
    """
    organized_dir = Path(organized_dir)
    base_dir = organized_dir.parent
    links_dir = base_dir / links_dir_name

    stats = {"moved": 0, "real_kept": 0, "errors": 0}
    details = []

    # Load organized link manifest for reliable detection
    manifest_path = organized_dir / "_organized_links.json"
    manifest_linked = set()
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in data.get("links", []):
                manifest_linked.add(entry.get("rel_path", ""))
        except (json.JSONDecodeError, OSError):
            pass

    for file_path in sorted(organized_dir.rglob("*")):
        if not file_path.is_file():
            continue

        # Skip metadata files
        if file_path.name.startswith("_"):
            continue

        rel = file_path.relative_to(organized_dir)
        rel_str = str(rel).replace("\\", "/")

        # Detect if this is a link: check manifest first, then filesystem
        is_link = rel_str in manifest_linked or file_path.is_symlink()

        if is_link:
            if dry_run:
                stats["moved"] += 1
                details.append(f"  WOULD MOVE: {rel}")
            else:
                dest = links_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(file_path), str(dest))
                    stats["moved"] += 1
                    details.append(f"  MOVED: {rel}")
                except OSError as e:
                    stats["errors"] += 1
                    details.append(f"  ERROR moving {rel}: {e}")
        else:
            stats["real_kept"] += 1

    # Clean up empty directories in organized/ (skip in dry run)
    if not dry_run:
        for dirpath in sorted(organized_dir.rglob("*"), reverse=True):
            if dirpath.is_dir() and not any(dirpath.iterdir()):
                try:
                    dirpath.rmdir()
                except OSError:
                    pass

    return stats, details


def join_links(organized_dir, links_dir_name="organized-links", dry_run=False):
    """Move linked files back from a parallel tree into organized/.

    Reverses the effect of separate_links() -- moves all files from
    the links directory back into organized/ preserving relative structure.

    Args:
        organized_dir: Path to the organized/ directory
        links_dir_name: Name of the sibling links directory
        dry_run: If True, preview without moving

    Returns: (stats_dict, details_list)
    """
    organized_dir = Path(organized_dir)
    base_dir = organized_dir.parent
    links_dir = base_dir / links_dir_name

    stats = {"moved": 0, "errors": 0}
    details = []

    if not links_dir.exists():
        return stats, details

    for file_path in sorted(links_dir.rglob("*")):
        if not file_path.is_file():
            continue

        rel = file_path.relative_to(links_dir)
        dest = organized_dir / rel

        if dry_run:
            stats["moved"] += 1
            details.append(f"  WOULD RESTORE: {rel}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                # Already exists in organized/ -- skip
                details.append(f"  SKIP (exists): {rel}")
                continue
            try:
                shutil.move(str(file_path), str(dest))
                stats["moved"] += 1
                details.append(f"  RESTORED: {rel}")
            except OSError as e:
                stats["errors"] += 1
                details.append(f"  ERROR restoring {rel}: {e}")

    # Clean up empty directories in links dir
    if not dry_run:
        for dirpath in sorted(links_dir.rglob("*"), reverse=True):
            if dirpath.is_dir() and not any(dirpath.iterdir()):
                try:
                    dirpath.rmdir()
                except OSError:
                    pass
        # Remove the links dir itself if empty
        if links_dir.exists() and not any(links_dir.iterdir()):
            try:
                links_dir.rmdir()
            except OSError:
                pass

    return stats, details
