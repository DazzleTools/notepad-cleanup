"""
Spike: Can we programmatically read text from Windows 11 Notepad tabs?

This script tests multiple approaches to extract text from open Notepad windows:
1. win32gui.EnumWindows — find all Notepad windows
2. pywinauto UIA backend — inspect the accessibility tree, enumerate tabs, read text
3. win32gui.SendMessage WM_GETTEXT — classic approach (may not work on Win11 Notepad)

Run this with one or more Notepad windows open (ideally with multiple tabs and some text).

Usage:
    python tests/one-offs/spike_notepad_uia.py
"""

import sys
import os
import time
import ctypes
import ctypes.wintypes

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import win32gui
import win32con
import win32process
import psutil


def separator(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


# ---------------------------------------------------------------------------
# APPROACH 1: win32gui — enumerate all Notepad windows
# ---------------------------------------------------------------------------
def find_notepad_windows_win32():
    """Use EnumWindows to find all top-level Notepad windows."""
    separator("APPROACH 1: win32gui.EnumWindows")

    notepad_windows = []

    def enum_callback(hwnd, results):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        class_name = win32gui.GetClassName(hwnd)

        # Get process name
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            proc_name = proc.name().lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            proc_name = ""

        if "notepad" in proc_name:
            results.append({
                "hwnd": hwnd,
                "title": title,
                "class_name": class_name,
                "pid": pid,
                "proc_name": proc_name,
            })

    win32gui.EnumWindows(enum_callback, notepad_windows)

    if not notepad_windows:
        print("No Notepad windows found!")
        return []

    print(f"Found {len(notepad_windows)} Notepad window(s):\n")
    for i, w in enumerate(notepad_windows):
        print(f"  [{i}] hwnd=0x{w['hwnd']:08X}  class={w['class_name']!r}")
        print(f"       title={w['title']!r}")
        print(f"       pid={w['pid']}  process={w['proc_name']}")
        print()

    return notepad_windows


# ---------------------------------------------------------------------------
# APPROACH 2: pywinauto UIA — inspect accessibility tree
# ---------------------------------------------------------------------------
def inspect_notepad_uia(notepad_windows):
    """Use pywinauto UIA backend to inspect Notepad's control tree."""
    separator("APPROACH 2: pywinauto UIA backend")

    try:
        from pywinauto import Desktop, Application
        from pywinauto.findwindows import ElementNotFoundError
    except ImportError:
        print("pywinauto not installed. pip install pywinauto")
        return

    desktop = Desktop(backend="uia")

    # Find all Notepad windows via UIA
    try:
        notepad_wrappers = desktop.windows(class_name_re=".*Notepad.*|.*ApplicationFrame.*")
        if not notepad_wrappers:
            # Try by process name instead
            notepad_wrappers = []
            for w in notepad_windows:
                try:
                    app = Application(backend="uia").connect(handle=w["hwnd"])
                    notepad_wrappers.append(app.top_window())
                except Exception as e:
                    print(f"  Could not connect to hwnd 0x{w['hwnd']:08X}: {e}")
    except Exception as e:
        print(f"  Error finding Notepad via UIA Desktop: {e}")
        # Fall back to connecting by handle
        notepad_wrappers = []
        for w in notepad_windows:
            try:
                app = Application(backend="uia").connect(handle=w["hwnd"])
                notepad_wrappers.append(app.top_window())
            except Exception as e:
                print(f"  Could not connect to hwnd 0x{w['hwnd']:08X}: {e}")

    if not notepad_wrappers:
        print("No Notepad windows found via UIA!")
        return

    for i, win in enumerate(notepad_wrappers):
        print(f"\n--- Window [{i}]: {win.window_text()!r} ---\n")

        # Print the full control tree (limited depth for readability)
        print("  Control tree (print_control_identifiers):")
        print("  " + "-" * 50)
        try:
            win.print_control_identifiers(depth=4)
        except Exception as e:
            print(f"  Error printing control tree: {e}")

        # Try to find tab controls
        print(f"\n  Looking for TabControl...")
        try:
            tabs = win.descendants(control_type="TabItem")
            if tabs:
                print(f"  Found {len(tabs)} tab(s):")
                for j, tab in enumerate(tabs):
                    tab_name = tab.window_text()
                    print(f"    Tab [{j}]: {tab_name!r}")
            else:
                print("  No TabItem controls found.")
        except Exception as e:
            print(f"  Error finding tabs: {e}")

        # Try to find text/edit/document controls
        print(f"\n  Looking for text content controls...")
        for ctrl_type in ["Edit", "Document", "Text"]:
            try:
                edits = win.descendants(control_type=ctrl_type)
                if edits:
                    print(f"  Found {len(edits)} {ctrl_type} control(s):")
                    for k, edit in enumerate(edits):
                        try:
                            # Try getting text via window_text()
                            text = edit.window_text()
                            preview = text[:200] if text else "(empty)"
                            print(f"    {ctrl_type}[{k}] window_text(): {preview!r}")
                        except Exception as e:
                            print(f"    {ctrl_type}[{k}] window_text() failed: {e}")

                        try:
                            # Try getting text via legacy_properties
                            val = edit.legacy_properties().get("Value", None)
                            if val:
                                preview = val[:200]
                                print(f"    {ctrl_type}[{k}] legacy Value: {preview!r}")
                        except Exception as e:
                            pass

                        try:
                            # Try the TextPattern
                            iface = edit.iface_text
                            if iface:
                                doc_range = iface.DocumentRange
                                text = doc_range.GetText(-1)
                                preview = text[:200] if text else "(empty)"
                                print(f"    {ctrl_type}[{k}] TextPattern: {preview!r}")
                        except Exception as e:
                            print(f"    {ctrl_type}[{k}] TextPattern failed: {e}")
            except Exception as e:
                print(f"  Error finding {ctrl_type} controls: {e}")

        # Try brute-force: get all descendants and check for text
        print(f"\n  Brute-force: checking all descendants for text content...")
        try:
            all_controls = win.descendants()
            text_found = False
            for ctrl in all_controls:
                try:
                    t = ctrl.window_text()
                    ctrl_type_name = ctrl.element_info.control_type
                    if t and len(t) > 20 and ctrl_type_name not in ("Window", "TitleBar", "MenuBar", "Menu", "MenuItem"):
                        preview = t[:200]
                        print(f"    [{ctrl_type_name}] {preview!r}")
                        text_found = True
                except Exception:
                    pass
            if not text_found:
                print("    No substantial text found in any descendant control.")
        except Exception as e:
            print(f"  Error during brute-force scan: {e}")


# ---------------------------------------------------------------------------
# APPROACH 3: SendMessage WM_GETTEXT (classic Win32 — probably won't work on Win11 Notepad)
# ---------------------------------------------------------------------------
def try_wm_gettext(notepad_windows):
    """Try the classic WM_GETTEXT approach on Notepad child windows."""
    separator("APPROACH 3: SendMessage WM_GETTEXT on child windows")

    for w in notepad_windows:
        hwnd = w["hwnd"]
        print(f"Window: {w['title']!r} (hwnd=0x{hwnd:08X})")

        # Enumerate child windows
        children = []

        def enum_child(child_hwnd, results):
            class_name = win32gui.GetClassName(child_hwnd)
            results.append((child_hwnd, class_name))
            return True

        win32gui.EnumChildWindows(hwnd, enum_child, children)

        if not children:
            print("  No child windows found.")
            continue

        print(f"  Found {len(children)} child window(s):")
        for child_hwnd, class_name in children:
            print(f"    child hwnd=0x{child_hwnd:08X}  class={class_name!r}")

            # Try WM_GETTEXT
            buf_size = 65536
            buf = ctypes.create_unicode_buffer(buf_size)
            length = ctypes.windll.user32.SendMessageW(
                child_hwnd, win32con.WM_GETTEXT, buf_size, buf
            )
            if length > 0:
                text = buf.value[:500]
                print(f"      WM_GETTEXT ({length} chars): {text!r}")
            else:
                print(f"      WM_GETTEXT: (no text)")

            # Try WM_GETTEXTLENGTH
            text_len = ctypes.windll.user32.SendMessageW(
                child_hwnd, win32con.WM_GETTEXTLENGTH, 0, 0
            )
            print(f"      WM_GETTEXTLENGTH: {text_len}")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Notepad UIA Spike Test")
    print(f"Python {sys.version}")
    print(f"Platform: {sys.platform}")
    print()

    # Step 1: Find windows
    notepad_windows = find_notepad_windows_win32()

    if not notepad_windows:
        print("\nPlease open at least one Notepad window with some text and run again.")
        sys.exit(1)

    # Step 2: UIA inspection
    inspect_notepad_uia(notepad_windows)

    # Step 3: Classic WM_GETTEXT
    try_wm_gettext(notepad_windows)

    separator("DONE")
    print("Review the output above to determine which approach works for text extraction.")
    print("Key questions:")
    print("  1. Did UIA find TabItem controls? (tab enumeration)")
    print("  2. Did any approach return actual text content?")
    print("  3. Which control type holds the text? (Edit, Document, RichEdit, etc.)")
