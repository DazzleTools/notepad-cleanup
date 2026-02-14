"""Two-phase text extraction from Notepad windows.

Phase 1 (silent): WM_GETTEXT on already-loaded RichEditD2DPT children.
Phase 2 (announced): UIA TabItem.Select() for unloaded tabs.
"""

import time

from pywinauto import Application

from .discovery import (
    get_richedit_children,
    read_richedit_text,
    get_foreground_hwnd,
    set_foreground,
)


def _make_tab_label(text, max_len=60):
    """Generate a tab label from the first line of text content."""
    if not text:
        return "(empty)"
    first_line = text.split("\n")[0].replace("\r", "").strip()
    if len(first_line) > max_len:
        return first_line[:max_len]
    return first_line or "(whitespace only)"


def extract_phase1(windows):
    """
    Silent extraction via WM_GETTEXT on loaded RichEditD2DPT children.
    No foreground changes, no focus stealing, completely invisible.

    Returns: {hwnd: [(tab_index, text, tab_label, child_hwnd)]}
    """
    results = {}

    for w in windows:
        hwnd = w["hwnd"]
        richedit_hwnds = get_richedit_children(hwnd)
        tabs = []

        for i, rh in enumerate(richedit_hwnds):
            text = read_richedit_text(rh)
            label = _make_tab_label(text)
            tabs.append((i, text, label, rh))

        results[hwnd] = tabs

    return results


def _normalize_for_dedup(text):
    """Normalize text for dedup comparison across extraction methods."""
    if not text:
        return ""
    # Normalize line endings and strip trailing whitespace per line
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def extract_phase2(windows, phase1_results, on_progress=None):
    """
    Extract unloaded tabs via UIA TabItem.Select().

    WARNING: This steals foreground focus and selects text in Notepad windows.
    Only call after user has been warned and confirmed.

    Args:
        windows: list of window dicts from find_notepad_windows()
        phase1_results: dict from extract_phase1()
        on_progress: optional callback(window_index, tab_index, tab_count)

    Returns: {hwnd: [(tab_index, text, tab_label, None)]} for newly extracted tabs
    """
    original_fg = get_foreground_hwnd()
    new_results = {}

    # Global dedup: build hash set from ALL Phase 1 text across ALL windows.
    # This prevents the same content from being re-extracted in different windows
    # (e.g. recently-visited tabs that appear loaded in multiple Notepad instances).
    global_hashes = set()
    for hwnd, tabs in phase1_results.items():
        for _, text, _, _ in tabs:
            if text:
                global_hashes.add(hash(_normalize_for_dedup(text)))

    from .discovery import get_tab_count

    for wi, w in enumerate(windows):
        hwnd = w["hwnd"]
        phase1_tabs = phase1_results.get(hwnd, [])
        phase1_count = len(phase1_tabs)

        total_tabs = get_tab_count(hwnd)

        # If Phase 1 got everything, skip
        if phase1_count >= total_tabs:
            continue

        # Connect via UIA — use window(handle=) not top_window() to avoid
        # cross-window bleed since all Notepad instances share one PID.
        try:
            app = Application(backend="uia").connect(handle=hwnd)
            win = app.window(handle=hwnd)
        except Exception:
            continue

        try:
            tab_items = win.descendants(control_type="TabItem")
        except Exception:
            tab_items = []

        if not tab_items:
            continue

        # Track which tab was originally active
        original_active = None
        for i, tab in enumerate(tab_items):
            try:
                if tab.is_selected():
                    original_active = i
                    break
            except Exception:
                pass

        new_tabs = []
        for i, tab in enumerate(tab_items):
            if on_progress:
                on_progress(wi, i, len(tab_items))

            try:
                tab.select()
                time.sleep(0.08)

                # Read via WM_GETTEXT (same method as Phase 1) for consistent
                # text format. Selecting a tab loads its RichEditD2DPT control.
                text = ""
                richedit_hwnds = get_richedit_children(hwnd)
                if richedit_hwnds:
                    # The active tab's RichEditD2DPT is typically the last one
                    # or the one that just appeared after select()
                    text = read_richedit_text(richedit_hwnds[-1])

                if not text:
                    continue

                # Global dedup — skip if any window already has this content
                norm_hash = hash(_normalize_for_dedup(text))
                if norm_hash in global_hashes:
                    continue

                label = _make_tab_label(text)
                new_tabs.append((phase1_count + len(new_tabs), text, label, None))
                global_hashes.add(norm_hash)

            except Exception:
                continue

        # Restore original active tab
        if original_active is not None and original_active < len(tab_items):
            try:
                tab_items[original_active].select()
            except Exception:
                pass

        if new_tabs:
            new_results[hwnd] = new_tabs

    # Restore original foreground window
    set_foreground(original_fg)

    return new_results


def merge_results(phase1, phase2):
    """Merge Phase 1 and Phase 2 results into a single dict."""
    merged = {}
    for hwnd, tabs in phase1.items():
        merged[hwnd] = list(tabs)
    for hwnd, tabs in phase2.items():
        if hwnd in merged:
            merged[hwnd].extend(tabs)
        else:
            merged[hwnd] = list(tabs)
    return merged
