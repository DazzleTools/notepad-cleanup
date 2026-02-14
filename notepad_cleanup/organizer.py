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
from pathlib import Path


PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "organize.md"


def load_prompt_template():
    """Load the organization prompt template."""
    return PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def generate_prompt(manifest_path):
    """
    Generate the AI organization prompt from a manifest file.

    Returns: formatted prompt string
    """
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    template = load_prompt_template()
    return template.format(
        window_count=manifest.get("window_count", 0),
        tab_count=manifest.get("tab_count", 0),
        total_chars=f"{manifest.get('total_chars', 0):,}",
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
                # poll with short sleeps so KeyboardInterrupt can fire
                while reader.is_alive():
                    reader.join(timeout=0.5)
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
