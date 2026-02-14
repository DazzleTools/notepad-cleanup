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

    for wi, w in enumerate(windows):
        hwnd = w["hwnd"]
        phase1_tabs = phase1_results.get(hwnd, [])
        phase1_count = len(phase1_tabs)

        # Get total tab count from NotepadTextBox children
        from .discovery import get_tab_count
        total_tabs = get_tab_count(hwnd)

        # If Phase 1 got everything, skip
        if phase1_count >= total_tabs:
            continue

        # Connect via UIA
        try:
            app = Application(backend="uia").connect(handle=hwnd)
            win = app.top_window()
        except Exception:
            continue

        # We need to Select() each tab and read the Document control.
        # We don't know which tabs are loaded vs unloaded by index,
        # so we iterate all tabs via UIA, read each, and skip duplicates.
        try:
            # Get tab count from NotepadTextBox (more reliable than UIA TabItem
            # which can bleed across windows)
            uia_tabs = win.children(control_type="Tab")
            if uia_tabs:
                tab_items = uia_tabs[0].children(control_type="TabItem")
            else:
                tab_items = []
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

        # Build set of Phase 1 text hashes for dedup
        phase1_hashes = set()
        for _, text, _, _ in phase1_tabs:
            if text:
                phase1_hashes.add(hash(text))

        new_tabs = []
        for i, tab in enumerate(tab_items):
            if on_progress:
                on_progress(wi, i, len(tab_items))

            try:
                tab.select()
                time.sleep(0.08)

                # Read Document control
                text = ""
                try:
                    docs = win.descendants(control_type="Document")
                    if docs:
                        text = docs[0].window_text()
                except Exception:
                    pass

                # Skip if we already have this text from Phase 1
                if text and hash(text) in phase1_hashes:
                    continue

                # Skip empty
                if not text:
                    continue

                label = _make_tab_label(text)
                new_tabs.append((phase1_count + len(new_tabs), text, label, None))
                phase1_hashes.add(hash(text))

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
