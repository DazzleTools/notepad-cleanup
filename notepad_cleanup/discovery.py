"""Window enumeration and tab discovery for Windows 11 Notepad."""

import ctypes
import ctypes.wintypes

import win32gui
import win32con
import win32process
import psutil


def find_notepad_windows():
    """
    Find all visible Notepad top-level windows.

    Returns list of dicts: {hwnd, title, pid, class_name, has_unsaved}
    """
    results = []

    def callback(hwnd, out):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            if "notepad" not in proc.name().lower():
                return
            title = win32gui.GetWindowText(hwnd)
            out.append({
                "hwnd": hwnd,
                "title": title,
                "pid": pid,
                "class_name": win32gui.GetClassName(hwnd),
                "has_unsaved": title.startswith("*"),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    win32gui.EnumWindows(callback, results)
    return results


def get_richedit_children(hwnd):
    """
    Get all RichEditD2DPT child window handles for a Notepad window.
    Each loaded tab has one RichEditD2DPT child containing its text.
    """
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


def get_tab_count(hwnd):
    """
    Estimate the number of tabs in a Notepad window.
    Uses NotepadTextBox child count as a proxy — each tab has one NotepadTextBox.
    """
    count = 0

    def callback(child_hwnd, _):
        nonlocal count
        if win32gui.GetClassName(child_hwnd) == "NotepadTextBox":
            count += 1
        return True

    win32gui.EnumChildWindows(hwnd, callback, None)
    return max(count, 1)


def get_foreground_hwnd():
    """Return the hwnd of the current foreground window."""
    return ctypes.windll.user32.GetForegroundWindow()


def set_foreground(hwnd):
    """Best-effort restore foreground window."""
    if hwnd:
        try:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
