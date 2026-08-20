"""Live acceptance check for the #17 fix (CRLF-fix DWP, check AC5).

Uses PRODUCTION code end to end: discovery.find_notepad_windows ->
get_richedit_children -> read_richedit_text (Phase 1, silent) ->
saver.save_extraction for ONE tab. Then finds that tab's counterpart in the
corrupted 2026-08-18 archive by normalized-content hash and verifies:
  - new file bytes: \r\n endings, zero \r\r\n
  - archive counterpart: contains \r\r\n (pre-fix corruption)
  - both hash identically under normalize_text (dedup works across boundary)
"""
import sys
from pathlib import Path
sys.path.insert(0, ".")

from notepad_cleanup.discovery import (find_notepad_windows,
                                       get_richedit_children,
                                       read_richedit_text)
from notepad_cleanup.saver import save_extraction
from notepad_cleanup.dedup import hash_text, normalize_text

ARCHIVE = Path(r"C:\Users\Extreme\Desktop\nc-2026-08-18__22-45-02")
SCRATCH = Path(r"C:\Users\Extreme\AppData\Local\Temp\claude"
               r"\C--code-notepad-cleanup-local"
               r"\0e30967a-d3ff-4389-bfc6-a5f45ff34da1\scratchpad"
               r"\live-one-tab")

# index the archive by normalized-content hash
archive_by_hash = {}
for f in sorted(ARCHIVE.glob("window*/tab*.txt")):
    try:
        archive_by_hash.setdefault(
            hash_text(f.read_text(encoding="utf-8", errors="replace")), f)
    except OSError:
        pass
print(f"archive files indexed: {len(archive_by_hash)}")

windows = find_notepad_windows()
print(f"notepad windows found: {len(windows)}")
if not windows:
    sys.exit("NO NOTEPAD RUNNING -- open Notepad and re-run")

# silently read loaded tabs until one matches the archive
pick = None
for w in windows:
    for i, rh in enumerate(get_richedit_children(w["hwnd"])):
        text = read_richedit_text(rh)
        if not text.strip():
            continue
        h = hash_text(text)
        if h in archive_by_hash:
            pick = (w, i, text, rh, archive_by_hash[h])
            break
    if pick:
        break

if not pick:
    sys.exit("no loaded tab matches the archive (tabs edited/closed since "
             "yesterday?) -- re-run after opening one of yesterday's notes")

w, i, text, rh, counterpart = pick
print(f"\nmatched live tab: window '{w['title'][:50]}' tab#{i+1}")
print(f"archive counterpart: {counterpart.relative_to(ARCHIVE)}")
print(f"internal text: {len(text)} chars, contains \r: {'\r' in text}")

# ONE-tab save through the real production writer
out_dir, manifest = save_extraction([w], {w["hwnd"]: [(i, text, "live-test", rh)]},
                                    output_dir=SCRATCH)
new_file = out_dir / "window01" / "tab01.txt"
new_raw = new_file.read_bytes()
old_raw = counterpart.read_bytes()

print(f"\nNEW  {new_file.name}: {len(new_raw)} bytes  "
      f"CRLF={new_raw.count(b'\r\n')}  CRCRLF={new_raw.count(b'\r\r\n')}")
print(f"OLD  {counterpart.name}: {len(old_raw)} bytes  "
      f"CRLF={old_raw.count(b'\r\n')}  CRCRLF={old_raw.count(b'\r\r\n')}")

h_new = hash_text(new_raw.decode('utf-8'))
h_old = hash_text(old_raw.decode('utf-8'))
print(f"\nnormalized hash new: {h_new[:16]}")
print(f"normalized hash old: {h_old[:16]}")

checks = {
    "new file has zero \r\r\n": new_raw.count(b"\r\r\n") == 0,
    "new file uses \r\n endings": new_raw.count(b"\r\n") > 0,
    "archive counterpart is corrupted (\r\r\n present)": old_raw.count(b"\r\r\n") > 0,
    "hashes match across boundary (dedup preserved)": h_new == h_old,
}
print()
ok = True
for name, passed in checks.items():
    print(f"  [{'OK' if passed else 'X '}] {name}")
    ok &= passed
print(f"\nAC5 (live one-tab check): {'PASS' if ok else 'FAIL'}")
