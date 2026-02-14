"""
Spike #3: Full two-phase extraction of ALL Notepad tabs.

Phase 1 (silent): Read all already-loaded RichEditD2DPT children via WM_GETTEXT.
Phase 2 (announced): Use UIA TabItem.Select() for remaining unloaded tabs.

Saves everything to %USERPROFILE%/Desktop/notepad-cleanup/windowNN/tabNN.txt
Writes a manifest.json for potential AI organization pass.

Usage:
    python tests/one-offs/spike_full_extraction.py
"""

import sys
import os
import json
import time
import ctypes
import ctypes.wintypes
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import win32gui
import win32con
import win32process
import psutil

from pywinauto import Application


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_foreground_hwnd():
    return ctypes.windll.user32.GetForegroundWindow()


def set_foreground(hwnd):
    """Best-effort restore foreground window."""
    try:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def find_notepad_windows():
    """Find all visible Notepad top-level windows."""
    results = []

    def callback(hwnd, out):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            if "notepad" in proc.name().lower():
                out.append({
                    "hwnd": hwnd,
                    "title": win32gui.GetWindowText(hwnd),
                    "class": win32gui.GetClassName(hwnd),
                    "pid": pid,
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    win32gui.EnumWindows(callback, results)
    return results


def get_richedit_children(hwnd):
    """Get all RichEditD2DPT child window handles."""
    children = []

    def callback(child_hwnd, out):
        if win32gui.GetClassName(child_hwnd) == "RichEditD2DPT":
            out.append(child_hwnd)
        return True

    win32gui.EnumChildWindows(hwnd, callback, children)
    return children


def read_richedit_text(child_hwnd):
    """Read full text from a RichEditD2DPT window via WM_GETTEXT."""
    text_len = ctypes.windll.user32.SendMessageW(
        child_hwnd, win32con.WM_GETTEXTLENGTH, 0, 0
    )
    if text_len <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(text_len + 1)
    ctypes.windll.user32.SendMessageW(
        child_hwnd, win32con.WM_GETTEXT, text_len + 1, buf
    )
    return buf.value


def get_uia_tab_info(hwnd):
    """
    Get tab names and active tab index for a specific window via UIA.
    Returns (tab_wrappers, tab_names, active_index).
    """
    try:
        app = Application(backend="uia").connect(handle=hwnd)
        win = app.top_window()

        # Only get DIRECT TabItem descendants that belong to this window
        # by checking their parent chain
        all_tabs = win.descendants(control_type="TabItem")

        # Filter: only keep tabs whose immediate parent's parent is our window
        # In Win11 Notepad, tabs are direct children of a TabControl inside the window
        tabs = []
        for tab in all_tabs:
            try:
                # Check that this tab's top-level parent matches our window
                parent = tab
                for _ in range(20):  # max depth
                    p = parent.parent()
                    if p is None:
                        break
                    if p.handle == hwnd:
                        tabs.append(tab)
                        break
                    parent = p
            except Exception:
                # If we can't walk the tree, include it anyway
                tabs.append(tab)
                break

        if not tabs:
            # Fallback: just use all tabs found
            tabs = all_tabs

        tab_names = [t.window_text() for t in tabs]

        # Find active tab
        active_idx = None
        for i, tab in enumerate(tabs):
            try:
                if tab.is_selected():
                    active_idx = i
                    break
            except Exception:
                pass

        return tabs, tab_names, active_idx, win
    except Exception as e:
        return [], [], None, None


def sanitize_filename(name, max_len=60):
    """Make a string safe for use as a filename."""
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in name)
    return safe.strip()[:max_len] or "unnamed"


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_window(hwnd, title, window_index, output_dir):
    """
    Extract all tabs from a single Notepad window.
    Phase 1: silent WM_GETTEXT on loaded children.
    Phase 2: UIA Select() for unloaded tabs.
    Returns extraction results for this window.
    """
    win_dir = output_dir / f"window{window_index:02d}"
    win_dir.mkdir(parents=True, exist_ok=True)

    # Get UIA tab info
    tabs, tab_names, active_idx, uia_win = get_uia_tab_info(hwnd)
    tab_count = len(tab_names) if tab_names else 1

    # Get loaded RichEditD2DPT children
    richedit_hwnds = get_richedit_children(hwnd)

    results = {
        "window_index": window_index,
        "hwnd": f"0x{hwnd:08X}",
        "title": title,
        "tab_count": tab_count,
        "tab_names": tab_names,
        "active_tab_index": active_idx,
        "preloaded_richedit": len(richedit_hwnds),
        "tabs": [],
    }

    # --- Phase 1: Read all loaded RichEditD2DPT children silently ---
    loaded_texts = {}  # child_hwnd -> text
    for rh in richedit_hwnds:
        text = read_richedit_text(rh)
        if text:
            loaded_texts[rh] = text

    # Match loaded texts to tab names by prefix comparison
    # Tab names are the first ~35 chars of content (with punctuation stripped)
    matched_tab_indices = set()
    matched_child_hwnds = set()

    for ti, tab_name in enumerate(tab_names):
        clean_name = tab_name
        for suffix in [". Modified.", ". Unmodified."]:
            clean_name = clean_name.replace(suffix, "")
        clean_name = clean_name.strip()

        for rh, text in loaded_texts.items():
            if rh in matched_child_hwnds:
                continue
            # Compare first 25 chars, stripping whitespace/newlines
            text_start = text[:50].replace("\r\n", "").replace("\r", "").replace("\n", "").replace("\xa0", " ").strip()
            if clean_name and text_start.startswith(clean_name[:25]):
                matched_tab_indices.add(ti)
                matched_child_hwnds.add(rh)

                tab_result = save_tab(win_dir, ti, tab_name, text, "silent_wm_gettext")
                results["tabs"].append(tab_result)
                break

    # Save any unmatched loaded texts as extra tabs
    extra_idx = tab_count
    for rh, text in loaded_texts.items():
        if rh not in matched_child_hwnds:
            # Try to match by active tab (window title often shows active tab content)
            tab_result = save_tab(win_dir, extra_idx, f"(loaded-unmatched-{rh})", text, "silent_wm_gettext")
            results["tabs"].append(tab_result)
            # Mark any single-tab windows as matched
            if tab_count == 1 and 0 not in matched_tab_indices:
                matched_tab_indices.add(0)
                tab_result["tab_index"] = 0
                tab_result["tab_name"] = tab_names[0] if tab_names else title
            else:
                extra_idx += 1

    # --- Phase 2: Select() for unloaded tabs ---
    unloaded_indices = [i for i in range(tab_count) if i not in matched_tab_indices]

    if unloaded_indices and tabs and uia_win:
        for ti in unloaded_indices:
            if ti >= len(tabs):
                continue
            tab = tabs[ti]
            tab_name = tab_names[ti]

            try:
                tab.select()
                time.sleep(0.08)  # wait for control creation

                # Read Document control
                text = ""
                try:
                    docs = uia_win.descendants(control_type="Document")
                    if docs:
                        text = docs[0].window_text()
                except Exception:
                    pass

                # Fallback: check for new RichEditD2DPT children
                if not text:
                    new_hwnds = get_richedit_children(hwnd)
                    for nh in new_hwnds:
                        if nh not in [r for r in richedit_hwnds]:
                            text = read_richedit_text(nh)
                            if text:
                                break

                if text:
                    tab_result = save_tab(win_dir, ti, tab_name, text, "uia_select")
                    results["tabs"].append(tab_result)
                else:
                    results["tabs"].append({
                        "tab_index": ti,
                        "tab_name": tab_name,
                        "chars": 0,
                        "method": "uia_select",
                        "status": "empty_or_failed",
                    })
            except Exception as e:
                results["tabs"].append({
                    "tab_index": ti,
                    "tab_name": tab_name,
                    "chars": 0,
                    "method": "uia_select",
                    "status": f"error: {e}",
                })

        # Restore original active tab
        if active_idx is not None and active_idx < len(tabs):
            try:
                tabs[active_idx].select()
            except Exception:
                pass

    # Sort tabs by index
    results["tabs"].sort(key=lambda t: t.get("tab_index", 999))

    # Write window metadata
    meta = {k: v for k, v in results.items() if k != "tabs"}
    meta["tabs_summary"] = [
        {k: v for k, v in t.items() if k != "text"}
        for t in results["tabs"]
    ]
    (win_dir / "_window_info.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return results


def save_tab(win_dir, tab_index, tab_name, text, method):
    """Save a tab's text to disk and return metadata."""
    clean_name = tab_name
    for suffix in [". Modified.", ". Unmodified."]:
        clean_name = clean_name.replace(suffix, "")
    safe_name = sanitize_filename(clean_name)
    filename = f"tab{tab_index+1:02d}_{safe_name}.txt"

    filepath = win_dir / filename
    filepath.write_text(text, encoding="utf-8")

    return {
        "tab_index": tab_index,
        "tab_name": tab_name,
        "filename": filename,
        "chars": len(text),
        "method": method,
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Full two-phase Notepad extraction")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip Phase 2 confirmation prompt (auto-proceed)")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = Path(os.environ.get("USERPROFILE", "")) / "Desktop" / f"notepad-cleanup-{timestamp}"

    print("=" * 70)
    print("  Spike #3: Full Two-Phase Notepad Extraction")
    print("=" * 70)
    print(f"  Output: {output_dir}")
    print()

    # --- Find all Notepad windows ---
    print("Phase 0: Finding Notepad windows...")
    notepad_windows = find_notepad_windows()
    print(f"  Found {len(notepad_windows)} Notepad window(s).")
    print()

    if not notepad_windows:
        print("No Notepad windows open.")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Phase 1: Silent extraction ---
    print("=" * 70)
    print("  Phase 1: Silent extraction (WM_GETTEXT on loaded tabs)")
    print("=" * 70)
    print()

    original_fg = get_foreground_hwnd()
    all_results = []
    phase1_tabs = 0
    phase1_chars = 0
    total_tabs = 0
    needs_phase2 = []

    for wi, w in enumerate(notepad_windows):
        hwnd = w["hwnd"]
        title = w["title"]

        # Pre-count tabs
        tabs, tab_names, active_idx, uia_win = get_uia_tab_info(hwnd)
        tab_count = len(tab_names) if tab_names else 1
        total_tabs += tab_count

        # Count loaded children
        richedit_hwnds = get_richedit_children(hwnd)
        loaded = len(richedit_hwnds)

        # Read loaded tabs silently
        loaded_chars = 0
        for rh in richedit_hwnds:
            text = read_richedit_text(rh)
            loaded_chars += len(text) if text else 0

        phase1_tabs += loaded
        phase1_chars += loaded_chars

        unloaded = tab_count - loaded
        if unloaded > 0:
            needs_phase2.append((wi, w, unloaded))

        status = "OK" if loaded >= tab_count else f"{loaded}/{tab_count}"
        print(f"  [{wi+1:2d}/{len(notepad_windows)}] [{status:>5s}] {title[:55]}")

    print()
    print(f"  Phase 1 result: {phase1_tabs}/{total_tabs} tabs readable silently ({phase1_chars:,} chars)")
    remaining = total_tabs - phase1_tabs
    print(f"  Remaining: {remaining} tabs need Phase 2 (tab switching)")
    print()

    # --- Phase 2: Announced extraction ---
    if remaining > 0:
        est_seconds = remaining * 0.15  # ~150ms per tab switch
        print("=" * 70)
        print(f"  Phase 2: Tab switching for {remaining} unloaded tabs")
        print(f"  Estimated time: ~{est_seconds:.0f} seconds")
        print(f"  WARNING: Notepad windows will briefly take focus.")
        print(f"  Please do not type or click until Phase 2 completes.")
        print("=" * 70)
        print()

        if not args.yes:
            input("  Press ENTER when ready (or Ctrl+C to skip Phase 2)... ")
        else:
            print("  (--yes flag: auto-proceeding)")
            time.sleep(1)
        print()

    # --- Full extraction (both phases) ---
    print("Extracting all windows...")
    print()

    phase2_tabs = 0
    phase2_chars = 0

    for wi, w in enumerate(notepad_windows):
        hwnd = w["hwnd"]
        title = w["title"]
        short = title[:55]

        t0 = time.perf_counter()
        result = extract_window(hwnd, title, wi + 1, output_dir)
        elapsed = time.perf_counter() - t0

        tab_count = result["tab_count"]
        extracted = sum(1 for t in result["tabs"] if t.get("status") == "ok")
        chars = sum(t.get("chars", 0) for t in result["tabs"])
        methods = set(t.get("method", "") for t in result["tabs"] if t.get("status") == "ok")

        all_results.append(result)
        if "uia_select" in methods:
            select_tabs = sum(1 for t in result["tabs"] if t.get("method") == "uia_select" and t.get("status") == "ok")
            select_chars = sum(t.get("chars", 0) for t in result["tabs"] if t.get("method") == "uia_select")
            phase2_tabs += select_tabs
            phase2_chars += select_chars

        print(f"  [{wi+1:2d}/{len(notepad_windows)}] {extracted}/{tab_count} tabs  {chars:>8,} chars  {elapsed:.1f}s  {short}")

    # Restore original foreground
    set_foreground(original_fg)

    # --- Summary ---
    total_extracted = sum(
        sum(1 for t in r["tabs"] if t.get("status") == "ok")
        for r in all_results
    )
    total_chars = sum(
        sum(t.get("chars", 0) for t in r["tabs"])
        for r in all_results
    )
    total_failed = sum(
        sum(1 for t in r["tabs"] if t.get("status") != "ok")
        for r in all_results
    )

    print()
    print("=" * 70)
    print("  EXTRACTION COMPLETE")
    print("=" * 70)
    print()
    print(f"  Windows:            {len(notepad_windows)}")
    print(f"  Total tabs:         {total_tabs}")
    print(f"  Tabs extracted:     {total_extracted}")
    print(f"  Tabs failed/empty:  {total_failed}")
    print(f"  Total characters:   {total_chars:,}")
    print(f"  Phase 1 (silent):   {phase1_tabs} tabs, {phase1_chars:,} chars")
    print(f"  Phase 2 (select):   {phase2_tabs} tabs, {phase2_chars:,} chars")
    print()

    if total_extracted == total_tabs:
        print("  100% EXTRACTION ACHIEVED")
    elif total_extracted + total_failed == total_tabs:
        print(f"  {total_extracted}/{total_tabs} extracted ({total_failed} empty/failed)")
    else:
        print(f"  WARNING: {total_tabs - total_extracted - total_failed} tabs unaccounted for")

    print(f"\n  Output: {output_dir}")

    # --- Global manifest ---
    manifest = {
        "timestamp": timestamp,
        "windows": len(notepad_windows),
        "total_tabs": total_tabs,
        "tabs_extracted": total_extracted,
        "tabs_failed": total_failed,
        "total_chars": total_chars,
        "phase1_silent": {"tabs": phase1_tabs, "chars": phase1_chars},
        "phase2_select": {"tabs": phase2_tabs, "chars": phase2_chars},
        "output_dir": str(output_dir),
        "windows_detail": [
            {
                "window_index": r["window_index"],
                "title": r["title"],
                "tab_count": r["tab_count"],
                "tabs": [
                    {k: v for k, v in t.items()}
                    for t in r["tabs"]
                ],
            }
            for r in all_results
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Manifest: {manifest_path}")
    print()
    print("  Next step: Feed this folder to Claude Code / Codex to organize and rename.")
