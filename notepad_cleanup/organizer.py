"""AI-powered organization of extracted Notepad text.

Builds a prompt with file contents inline, asks Claude for a JSON plan,
then executes the plan locally (copy/rename/group).
"""

import json
import os
import signal
import shutil
import subprocess
import sys
from pathlib import Path


PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "organize.md"

# Max chars to include inline per file; larger files get a preview
PREVIEW_LIMIT = 2000
# Files above this size are "large" and only get a short preview
LARGE_FILE_THRESHOLD = 50000


def load_prompt_template():
    """Load the organization prompt template."""
    return PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def build_file_listing(manifest_path):
    """
    Build a text listing of all extracted files with their content inline.

    Returns: (listing_text, file_count)
    """
    manifest_path = Path(manifest_path)
    base_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    lines = []
    file_count = 0

    for win in manifest.get("windows", []):
        folder = win["folder"]
        title = win.get("title", "Unknown")
        has_unsaved = win.get("has_unsaved", False)

        for tab in win.get("tabs", []):
            filename = tab.get("filename")
            if not filename:
                continue  # empty tab

            file_count += 1
            rel_path = f"{folder}/{filename}"
            chars = tab.get("chars", 0)
            label = tab.get("label", "")
            content_type = tab.get("content_type", "unknown")

            # Read the actual file
            file_path = base_dir / folder / filename
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = "(could not read file)"

            lines.append(f"### {rel_path}")
            lines.append(f"- Window title: {title}")
            lines.append(f"- Tab label: {label}")
            lines.append(f"- Content type hint: {content_type}")
            lines.append(f"- Size: {chars} chars")
            if has_unsaved:
                lines.append("- Has unsaved changes: yes")

            if chars > LARGE_FILE_THRESHOLD:
                preview = text[:500].rstrip()
                lines.append(f"- **PREVIEW** (file too large to include fully):")
                lines.append(f"```\n{preview}\n```")
            elif chars > PREVIEW_LIMIT:
                lines.append(f"```\n{text[:PREVIEW_LIMIT].rstrip()}\n... ({chars - PREVIEW_LIMIT} more chars)\n```")
            else:
                lines.append(f"```\n{text}\n```")

            lines.append("")

    return "\n".join(lines), file_count


def generate_prompt(manifest_path):
    """
    Generate the AI organization prompt with file contents inline.

    Args:
        manifest_path: Path to manifest.json

    Returns: formatted prompt string
    """
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    file_listing, _ = build_file_listing(manifest_path)

    template = load_prompt_template()
    return template.format(
        window_count=manifest.get("window_count", 0),
        tab_count=manifest.get("tab_count", 0),
        total_chars=f"{manifest.get('total_chars', 0):,}",
        file_listing=file_listing,
    )


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
    Invoke Claude Code CLI in non-interactive mode.

    Returns: (success, output_text)
    """
    claude_path = find_claude_cli()
    if not claude_path:
        return False, "Claude Code CLI not found. Install from https://claude.ai/claude-code"

    working_dir = Path(working_dir)

    # Save prompt to file for reference / manual use
    prompt_file = working_dir / "_organize_prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")

    # Pipe prompt via stdin to avoid Windows 32K command-line length limit
    # -p with no argument reads from stdin
    cmd = [
        claude_path,
        "--output-format", "text",
        "-p",
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
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            # Send prompt via stdin then close
            process.stdin.write(prompt)
            process.stdin.close()

            output_lines = []
            try:
                for line in process.stdout:
                    output_lines.append(line)
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    if log_fh:
                        log_fh.write(line)
                        log_fh.flush()
                process.wait(timeout=600)
            except KeyboardInterrupt:
                process.kill()
                process.wait()
                return False, "Cancelled by user (Ctrl+C)"
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return False, "Claude CLI timed out after 10 minutes"

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
                input=prompt,
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
        # Remove first line (```json or ```) and last line (```)
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


def execute_plan(plan, base_dir):
    """
    Execute the organization plan by copying/renaming files.

    Args:
        plan: list of dicts with source, category, new_name, reason
        base_dir: path to the extraction output directory

    Returns: (summary_text, stats_dict)
    """
    base_dir = Path(base_dir)
    reorg_dir = base_dir / "_reorganized"
    reorg_dir.mkdir(exist_ok=True)

    stats = {"copied": 0, "quick_notes": 0, "skipped": 0, "errors": 0}
    categories = {}
    quick_notes = []
    details = []

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

        # Quick notes get grouped
        if category == "quick-notes" or new_name is None:
            try:
                text = source_path.read_text(encoding="utf-8", errors="replace")
                quick_notes.append((source, text.strip(), reason))
                stats["quick_notes"] += 1
            except Exception as e:
                stats["errors"] += 1
                details.append(f"  ERROR reading {source}: {e}")
            continue

        # Create category folder and copy
        cat_dir = reorg_dir / category
        cat_dir.mkdir(exist_ok=True)

        dest_path = cat_dir / new_name
        try:
            shutil.copy2(str(source_path), str(dest_path))
            stats["copied"] += 1
            categories.setdefault(category, []).append(new_name)
            details.append(f"  {source} -> {category}/{new_name}")
        except Exception as e:
            stats["errors"] += 1
            details.append(f"  ERROR copying {source}: {e}")

    # Write quick notes file
    if quick_notes:
        qn_path = reorg_dir / "quick-notes.md"
        lines = ["# Quick Notes\n", "Short notes extracted from Notepad tabs.\n"]
        for source, text, reason in quick_notes:
            lines.append(f"## From {source}")
            if reason:
                lines.append(f"*{reason}*\n")
            lines.append(f"{text}\n")
        qn_path.write_text("\n".join(lines), encoding="utf-8")

    # Write summary
    summary_lines = ["# Organization Summary\n"]
    summary_lines.append(f"- **Files organized**: {stats['copied'] + stats['quick_notes']}")
    summary_lines.append(f"- **Categories**: {len(categories)}")
    summary_lines.append(f"- **Quick notes grouped**: {stats['quick_notes']}")
    if stats["errors"]:
        summary_lines.append(f"- **Errors**: {stats['errors']}")
    summary_lines.append("")

    summary_lines.append("## Categories\n")
    for cat, files in sorted(categories.items()):
        summary_lines.append(f"### {cat} ({len(files)} files)")
        for f in files:
            summary_lines.append(f"- {f}")
        summary_lines.append("")

    if quick_notes:
        summary_lines.append(f"### quick-notes ({len(quick_notes)} entries)")
        summary_lines.append("- quick-notes.md")
        summary_lines.append("")

    summary_lines.append("## File Mapping\n")
    summary_lines.extend(details)

    summary_text = "\n".join(summary_lines)
    summary_path = reorg_dir / "_summary.md"
    summary_path.write_text(summary_text, encoding="utf-8")

    return summary_text, stats


def save_prompt_to_file(prompt, output_dir):
    """Save the generated prompt to a file for manual use."""
    output_dir = Path(output_dir)
    prompt_file = output_dir / "_organize_prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    return prompt_file
