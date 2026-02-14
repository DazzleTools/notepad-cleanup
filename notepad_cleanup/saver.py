"""Save extracted text to disk with manifest."""

import json
import re
from datetime import datetime
from pathlib import Path


def sanitize_filename(name, max_len=60):
    """Make a string safe for use as a filename."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    safe = safe.strip(". ")[:max_len]
    return safe or "unnamed"


def detect_file_type(text):
    """Guess what kind of content this is based on text analysis."""
    if not text or len(text.strip()) == 0:
        return "empty"
    first_line = text.split("\n")[0].strip()

    # Config files
    if first_line.startswith("[") and "]" in first_line:
        return "config"

    # Code patterns
    code_indicators = [
        "import ", "from ", "def ", "class ", "function ", "const ",
        "var ", "let ", "#include", "#!/", "package ", "public class",
    ]
    for indicator in code_indicators:
        if indicator in text[:500]:
            return "code"

    # JSON
    stripped = text.strip()
    if (stripped.startswith("{") and stripped.endswith("}")) or \
       (stripped.startswith("[") and stripped.endswith("]")):
        return "data"

    # Markdown
    if first_line.startswith("# ") or "\n## " in text[:500]:
        return "markdown"

    # Short note
    if len(text) < 200:
        return "short-note"

    return "text"


def save_extraction(windows, extraction_results, output_dir=None):
    """
    Save all extracted text to disk.

    Args:
        windows: list of window dicts from find_notepad_windows()
        extraction_results: merged dict from extractor.merge_results()
        output_dir: Path to output directory (auto-generated if None)

    Returns: Path to the output directory
    """
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        desktop = Path.home() / "Desktop"
        output_dir = desktop / f"notepad-cleanup-{timestamp}"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    hwnd_to_window = {w["hwnd"]: w for w in windows}
    manifest_windows = []

    for wi, (hwnd, tabs) in enumerate(extraction_results.items()):
        w = hwnd_to_window.get(hwnd, {})
        win_dir = output_dir / f"window{wi+1:02d}"
        win_dir.mkdir(exist_ok=True)

        tab_entries = []
        for ti, (tab_index, text, label, child_hwnd) in enumerate(tabs):
            if not text:
                tab_entries.append({
                    "index": ti + 1,
                    "filename": None,
                    "label": label,
                    "chars": 0,
                    "content_type": "empty",
                    "method": "silent" if child_hwnd else "select",
                })
                continue

            filename = f"tab{ti+1:02d}.txt"
            filepath = win_dir / filename
            filepath.write_text(text, encoding="utf-8")

            tab_entries.append({
                "index": ti + 1,
                "filename": filename,
                "label": label,
                "chars": len(text),
                "content_type": detect_file_type(text),
                "method": "silent" if child_hwnd else "select",
            })

        # Window info
        window_info = {
            "window_index": wi + 1,
            "folder": f"window{wi+1:02d}",
            "title": w.get("title", ""),
            "has_unsaved": w.get("has_unsaved", False),
            "tab_count": len(tabs),
            "tabs": tab_entries,
        }
        manifest_windows.append(window_info)

        # Per-window info file
        (win_dir / "_info.json").write_text(
            json.dumps(window_info, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # Global manifest
    total_tabs = sum(len(tabs) for tabs in extraction_results.values())
    total_chars = sum(
        sum(len(text) for _, text, _, _ in tabs if text)
        for tabs in extraction_results.values()
    )

    manifest = {
        "version": "1.0",
        "timestamp": datetime.now().isoformat(),
        "window_count": len(extraction_results),
        "tab_count": total_tabs,
        "total_chars": total_chars,
        "windows": manifest_windows,
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return output_dir, manifest
