"""
Spike #2: Test UIA TabItem.Select() obtrusiveness and full text extraction.

Tests:
1. Can we Select() tabs without bringing the window to foreground?
2. After Select(), can we read the full text from the Document control?
3. What's the latency per tab switch?
4. Can we restore the original active tab afterward?

Picks ONE Notepad window with the most tabs for maximum coverage.
Saves extracted text to %USERPROFILE%/Desktop/notepad-spike/

Usage:
    python tests/one-offs/spike_tab_switching.py
"""

import sys
import os
import json
import time
import ctypes
import ctypes.wintypes
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import win32gui
import win32con
import win32process
import psutil

from pywinauto import Desktop, Application


def get_foreground_hwnd():
    """Return the hwnd of the current foreground window."""
    return ctypes.windll.user32.GetForegroundWindow()


def get_foreground_info():
    """Return (hwnd, title) of the current foreground window."""
    hwnd = get_foreground_hwnd()
    title = win32gui.GetWindowText(hwnd) if hwnd else "(none)"
    return hwnd, title


def find_notepad_windows():
    """Find all Notepad top-level windows via EnumWindows."""
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


def count_richedit_children(hwnd):
    """Count RichEditD2DPT child windows (indicates loaded tabs)."""
    children = []

    def callback(child_hwnd, out):
        if win32gui.GetClassName(child_hwnd) == "RichEditD2DPT":
            out.append(child_hwnd)
        return True

    win32gui.EnumChildWindows(hwnd, callback, children)
    return children


def pick_best_window(notepad_windows):
    """Pick the Notepad window with the most tabs for testing."""
    desktop = Desktop(backend="uia")
    best = None
    best_tab_count = 0

    for w in notepad_windows:
        try:
            app = Application(backend="uia").connect(handle=w["hwnd"])
            win = app.top_window()
            tabs = win.descendants(control_type="TabItem")
            tab_count = len(tabs)
            richedit_count = len(count_richedit_children(w["hwnd"]))

            if tab_count > best_tab_count:
                best_tab_count = tab_count
                best = {
                    **w,
                    "uia_window": win,
                    "tab_count": tab_count,
                    "loaded_tabs": richedit_count,
                }
        except Exception as e:
            print(f"  Skipping hwnd 0x{w['hwnd']:08X}: {e}")

    return best


def extract_all_tabs(window_info):
    """
    Core test: iterate all tabs via Select(), extract text, measure impact.

    Returns a list of tab results and timing/obtrusiveness data.
    """
    win = window_info["uia_window"]
    hwnd = window_info["hwnd"]

    # Get all TabItems
    tabs = win.descendants(control_type="TabItem")
    tab_count = len(tabs)

    # Identify the currently active tab
    active_tab_idx = None
    for i, tab in enumerate(tabs):
        try:
            # TabItem with SelectionItemPattern — is_selected()
            if tab.is_selected():
                active_tab_idx = i
                break
        except Exception:
            pass

    if active_tab_idx is None:
        # Fallback: match window title against tab names
        win_title = window_info["title"]
        for i, tab in enumerate(tabs):
            tab_name = tab.window_text().replace(". Modified.", "").replace(". Unmodified.", "")
            if tab_name in win_title:
                active_tab_idx = i
                break

    print(f"  Active tab index: {active_tab_idx}")
    print(f"  Total tabs: {tab_count}")
    print(f"  Pre-loaded RichEditD2DPT children: {window_info['loaded_tabs']}")
    print()

    # Record foreground before we start
    fg_before_hwnd, fg_before_title = get_foreground_info()
    print(f"  Foreground before: 0x{fg_before_hwnd:08X} ({fg_before_title[:60]})")
    print()

    results = []
    foreground_changes = 0

    for i, tab in enumerate(tabs):
        tab_name = tab.window_text()
        is_original_active = (i == active_tab_idx)

        print(f"  Tab [{i}/{tab_count-1}]: {tab_name!r}")

        # Record pre-loaded state
        richedit_before = count_richedit_children(hwnd)

        # --- THE KEY TEST: Always Select the tab (even if it was active,
        # because a prior iteration may have switched away from it) ---
        t_start = time.perf_counter()

        try:
            tab.select()
        except Exception as e:
            print(f"    Select() FAILED: {e}")
            results.append({
                "index": i,
                "tab_name": tab_name,
                "error": str(e),
            })
            continue

        # Immediately try to restore foreground to original window
        if fg_before_hwnd and fg_before_hwnd != hwnd:
            ctypes.windll.user32.SetForegroundWindow(fg_before_hwnd)

        # Small delay for control creation
        time.sleep(0.05)

        t_select = time.perf_counter()

        # Check if foreground was successfully restored
        fg_after_hwnd, fg_after_title = get_foreground_info()
        fg_changed = (fg_after_hwnd != fg_before_hwnd)
        fg_is_notepad = (fg_after_hwnd == hwnd)
        if fg_changed:
            foreground_changes += 1
            if fg_is_notepad:
                print(f"    FG: Notepad took focus (restore failed)")
            else:
                print(f"    FG: Now 0x{fg_after_hwnd:08X} ({fg_after_title[:40]})")
        else:
            print(f"    FG: Restored to original (non-obtrusive!)")

        # Check if new RichEditD2DPT appeared
        richedit_after = count_richedit_children(hwnd)
        new_children = len(richedit_after) - len(richedit_before)

        # Now read text from Document control
        text = ""
        read_method = "none"
        try:
            docs = win.descendants(control_type="Document")
            if docs:
                text = docs[0].window_text()
                read_method = "UIA Document.window_text()"
        except Exception as e:
            print(f"    UIA Document read failed: {e}")

        # Fallback: try WM_GETTEXT on newest RichEditD2DPT
        if not text and richedit_after:
            try:
                target_hwnd = richedit_after[-1]  # newest child
                buf_size = ctypes.windll.user32.SendMessageW(
                    target_hwnd, win32con.WM_GETTEXTLENGTH, 0, 0
                ) + 1
                buf = ctypes.create_unicode_buffer(buf_size)
                ctypes.windll.user32.SendMessageW(
                    target_hwnd, win32con.WM_GETTEXT, buf_size, buf
                )
                text = buf.value
                read_method = "WM_GETTEXT"
            except Exception as e:
                print(f"    WM_GETTEXT fallback failed: {e}")

        t_read = time.perf_counter()

        select_ms = (t_select - t_start) * 1000
        read_ms = (t_read - t_select) * 1000
        total_ms = (t_read - t_start) * 1000

        char_count = len(text)
        preview = text[:80].replace("\r\n", " ").replace("\r", " ").replace("\n", " ") if text else "(empty)"

        print(f"    Chars: {char_count}  |  Select: {select_ms:.1f}ms  |  Read: {read_ms:.1f}ms  |  Total: {total_ms:.1f}ms")
        print(f"    Method: {read_method}  |  New children: {new_children}  |  FG changed: {fg_changed}")
        print(f"    Preview: {preview!r}")
        print()

        results.append({
            "index": i,
            "tab_name": tab_name,
            "char_count": char_count,
            "text": text,
            "read_method": read_method,
            "select_ms": round(select_ms, 1),
            "read_ms": round(read_ms, 1),
            "total_ms": round(total_ms, 1),
            "foreground_changed": fg_changed,
            "new_richedit_children": new_children,
            "was_original_active": is_original_active,
        })

    # --- Restore original active tab ---
    if active_tab_idx is not None and active_tab_idx < len(tabs):
        print(f"  Restoring original active tab [{active_tab_idx}]...")
        try:
            tabs[active_tab_idx].select()
            print(f"  Restored.")
        except Exception as e:
            print(f"  Restore FAILED: {e}")

    # Final foreground check
    fg_final_hwnd, fg_final_title = get_foreground_info()
    fg_restored = (fg_final_hwnd == fg_before_hwnd)

    summary = {
        "total_tabs": tab_count,
        "tabs_extracted": sum(1 for r in results if r.get("char_count", 0) > 0),
        "total_chars": sum(r.get("char_count", 0) for r in results),
        "foreground_changes": foreground_changes,
        "foreground_restored": fg_restored,
        "avg_select_ms": round(sum(r.get("select_ms", 0) for r in results) / max(len(results), 1), 1),
        "avg_total_ms": round(sum(r.get("total_ms", 0) for r in results) / max(len(results), 1), 1),
        "original_active_tab": active_tab_idx,
    }

    return results, summary


def save_output(window_info, tab_results, summary):
    """Save extracted text to %USERPROFILE%/Desktop/notepad-spike/"""
    desktop_path = Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "notepad-spike"
    desktop_path.mkdir(parents=True, exist_ok=True)

    # Save each tab's text
    for r in tab_results:
        if r.get("char_count", 0) == 0:
            continue
        # Clean tab name for filename
        tab_name = r["tab_name"]
        # Remove "Modified"/"Unmodified" suffix
        for suffix in [". Modified.", ". Unmodified."]:
            tab_name = tab_name.replace(suffix, "")
        # Sanitize for filesystem
        safe_name = "".join(c if c.isalnum() or c in " -_." else "_" for c in tab_name)
        safe_name = safe_name.strip()[:60] or f"tab{r['index']}"
        filename = f"tab{r['index']:02d}_{safe_name}.txt"

        filepath = desktop_path / filename
        filepath.write_text(r["text"], encoding="utf-8")
        print(f"  Saved: {filepath.name} ({r['char_count']} chars)")

    # Save manifest
    manifest = {
        "window": {
            "hwnd": f"0x{window_info['hwnd']:08X}",
            "title": window_info["title"],
            "pid": window_info["pid"],
            "tab_count": window_info["tab_count"],
            "preloaded_tabs": window_info["loaded_tabs"],
        },
        "summary": summary,
        "tabs": [
            {k: v for k, v in r.items() if k != "text"}
            for r in tab_results
        ],
    }
    manifest_path = desktop_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved: manifest.json")

    return desktop_path


def silent_extract_all_windows(notepad_windows):
    """
    APPROACH B: Pure WM_GETTEXT on existing RichEditD2DPT children.
    No Select(), no foreground changes, no focus stealing.
    Only reads tabs that Notepad has already loaded into memory.
    """
    print("=" * 70)
    print("  APPROACH B: Silent WM_GETTEXT (no tab switching)")
    print("=" * 70)
    print()

    all_results = []
    total_tabs_uia = 0
    total_loaded = 0
    total_chars = 0

    for w in notepad_windows:
        hwnd = w["hwnd"]
        title = w["title"]

        # Get UIA tab info (names only — this is non-obtrusive)
        tab_names = []
        try:
            app = Application(backend="uia").connect(handle=hwnd)
            win = app.top_window()
            tabs = win.descendants(control_type="TabItem")
            tab_names = [t.window_text() for t in tabs]
        except Exception:
            tab_names = [title]

        total_tabs_uia += len(tab_names)

        # Get all RichEditD2DPT children via WM_GETTEXT
        richedit_hwnds = count_richedit_children(hwnd)
        total_loaded += len(richedit_hwnds)

        window_texts = []
        for rh in richedit_hwnds:
            try:
                text_len = ctypes.windll.user32.SendMessageW(
                    rh, win32con.WM_GETTEXTLENGTH, 0, 0
                )
                if text_len > 0:
                    buf = ctypes.create_unicode_buffer(text_len + 1)
                    ctypes.windll.user32.SendMessageW(
                        rh, win32con.WM_GETTEXT, text_len + 1, buf
                    )
                    window_texts.append(buf.value)
                    total_chars += text_len
                else:
                    window_texts.append("")
            except Exception as e:
                window_texts.append(f"(error: {e})")

        # Correlate: match RichEditD2DPT text to tab names by prefix
        tab_text_pairs = []
        used_texts = set()
        for tab_name in tab_names:
            clean_name = tab_name.replace(". Modified.", "").replace(". Unmodified.", "")
            matched = False
            for j, text in enumerate(window_texts):
                if j in used_texts:
                    continue
                # Tab name is first ~35 chars of content
                if text and clean_name and text[:30].replace("\r\n", "").replace("\r", "").replace("\n", "").startswith(clean_name[:25]):
                    tab_text_pairs.append((tab_name, text, "matched"))
                    used_texts.add(j)
                    matched = True
                    break
            if not matched:
                tab_text_pairs.append((tab_name, None, "unloaded"))

        # Any remaining unmatched texts
        for j, text in enumerate(window_texts):
            if j not in used_texts and text:
                tab_text_pairs.append((f"(unmatched-child-{j})", text, "orphan"))

        all_results.append({
            "hwnd": hwnd,
            "title": title,
            "tab_names": tab_names,
            "tab_count": len(tab_names),
            "loaded_count": len(richedit_hwnds),
            "pairs": tab_text_pairs,
        })

    # Print summary
    tabs_with_text = sum(
        1 for wr in all_results
        for _, text, status in wr["pairs"]
        if text and status != "unloaded"
    )
    tabs_unloaded = sum(
        1 for wr in all_results
        for _, text, status in wr["pairs"]
        if status == "unloaded"
    )

    print(f"  Windows scanned:      {len(notepad_windows)}")
    print(f"  Total UIA tabs:       {total_tabs_uia}")
    print(f"  Loaded RichEditD2DPT: {total_loaded}")
    print(f"  Tabs with text:       {tabs_with_text}")
    print(f"  Tabs unloaded:        {tabs_unloaded}")
    print(f"  Total characters:     {total_chars:,}")
    print(f"  Coverage:             {tabs_with_text}/{total_tabs_uia} ({tabs_with_text/max(total_tabs_uia,1)*100:.0f}%)")
    print()

    # Show per-window breakdown
    print("  Per-window breakdown:")
    for wr in all_results:
        loaded = sum(1 for _, t, s in wr["pairs"] if t and s != "unloaded")
        total = wr["tab_count"]
        indicator = "OK" if loaded == total else f"PARTIAL ({loaded}/{total})"
        print(f"    [{indicator}] {wr['title'][:60]}")
        for tab_name, text, status in wr["pairs"]:
            if status == "unloaded":
                print(f"           {tab_name[:50]} -> (unloaded, needs tab switch)")
            elif text:
                preview = text[:60].replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
                print(f"           {tab_name[:50]} -> {len(text)} chars")
            else:
                print(f"           {tab_name[:50]} -> (empty)")

    print()
    return all_results, {
        "windows": len(notepad_windows),
        "total_tabs": total_tabs_uia,
        "loaded_tabs": total_loaded,
        "tabs_with_text": tabs_with_text,
        "tabs_unloaded": tabs_unloaded,
        "total_chars": total_chars,
        "coverage_pct": round(tabs_with_text / max(total_tabs_uia, 1) * 100, 1),
    }


def save_silent_output(all_results, summary):
    """Save silently-extracted text to %USERPROFILE%/Desktop/notepad-spike/"""
    desktop_path = Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "notepad-spike-silent"
    desktop_path.mkdir(parents=True, exist_ok=True)

    file_count = 0
    for wi, wr in enumerate(all_results):
        win_dir = desktop_path / f"notepad{wi+1:02d}"
        win_dir.mkdir(exist_ok=True)

        for ti, (tab_name, text, status) in enumerate(wr["pairs"]):
            if not text or status == "unloaded":
                continue
            clean_name = tab_name
            for suffix in [". Modified.", ". Unmodified."]:
                clean_name = clean_name.replace(suffix, "")
            safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in clean_name).strip()[:60]
            safe = safe or f"tab{ti}"
            filepath = win_dir / f"tab{ti+1:02d}_{safe}.txt"
            filepath.write_text(text, encoding="utf-8")
            file_count += 1

        # Window metadata
        meta = {
            "hwnd": f"0x{wr['hwnd']:08X}",
            "title": wr["title"],
            "tab_count": wr["tab_count"],
            "loaded_count": wr["loaded_count"],
            "tabs": [
                {"name": tn, "status": st, "chars": len(tx) if tx else 0}
                for tn, tx, st in wr["pairs"]
            ],
        }
        (win_dir / "_window_info.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Global manifest
    manifest = {"summary": summary}
    (desktop_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"  Saved {file_count} files across {len(all_results)} window folders")
    return desktop_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Spike #2: Tab extraction tests")
    parser.add_argument("--mode", choices=["select", "silent", "both"], default="silent",
                        help="select=UIA Select (obtrusive), silent=WM_GETTEXT only, both=run both")
    args = parser.parse_args()

    print("=" * 70)
    print("  Spike #2: Tab Extraction Test")
    print("=" * 70)
    print()

    # Find all Notepad windows
    print("Finding Notepad windows...")
    notepad_windows = find_notepad_windows()
    print(f"Found {len(notepad_windows)} Notepad window(s).\n")

    if not notepad_windows:
        print("No Notepad windows open. Please open Notepad with multiple tabs.")
        sys.exit(1)

    # --- Mode: Select (obtrusive) ---
    if args.mode in ("select", "both"):
        print("\nScanning for best test window (most tabs)...")
        best = pick_best_window(notepad_windows)

        if best:
            print(f"\nSelected: {best['title']!r} ({best['tab_count']} tabs)\n")
            print("=" * 70)
            print("  APPROACH A: UIA Select (obtrusive)")
            print("=" * 70)
            print()
            tab_results, summary = extract_all_tabs(best)

            print()
            print(f"  Tabs: {summary['tabs_extracted']}/{summary['total_tabs']}")
            print(f"  Chars: {summary['total_chars']:,}")
            print(f"  FG changes: {summary['foreground_changes']}")
            print(f"  Avg time/tab: {summary['avg_total_ms']}ms")
            print()

            print("Saving Approach A output...")
            out_path = save_output(best, tab_results, summary)
            print(f"  -> {out_path}\n")

    # --- Mode: Silent (non-obtrusive) ---
    if args.mode in ("silent", "both"):
        all_results, silent_summary = silent_extract_all_windows(notepad_windows)

        print("Saving Approach B output...")
        out_path = save_silent_output(all_results, silent_summary)
        print(f"  -> {out_path}\n")

        print("=" * 70)
        print("  FINAL VERDICT")
        print("=" * 70)
        print()
        print(f"  Silent extraction coverage: {silent_summary['coverage_pct']}%")
        print(f"  ({silent_summary['tabs_with_text']} of {silent_summary['total_tabs']} tabs readable without any tab switching)")
        if silent_summary['tabs_unloaded'] > 0:
            print(f"  {silent_summary['tabs_unloaded']} tabs need tab switching (Notepad hasn't loaded them yet)")
        print()
