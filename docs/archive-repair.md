# Archive Repair: Line-Ending Corruption in Pre-v0.2.6 Sessions

## What happened

Every version before v0.2.6 wrote extracted tab files with doubled carriage returns: lines end in `\r\r\n` instead of `\r\n` ([#17]). The extraction text arrived from the Notepad control with `\r\n` endings, and a text-mode file write translated the `\n` into `\r\n` again. In a typical session, every multi-line file is affected (files without line breaks were untouched, as were tabs whose source files used Unix `\n` endings).

v0.2.6 fixed the writer: text is normalized to `\n` internally at the extraction boundary and serialized explicitly as `\r\n` on disk. New extractions are byte-identical to what Notepad itself would save.

## Symptoms in old archives

- Files render **double-spaced** in most editors (a lone `\r` counts as a line break)
- `compare` will **not exact-match** an old archived copy against a clean re-extraction of the same note -- the phantom newlines change the content hash. Small files may still surface as near-matches; larger ones will not match at all
- Byte sizes are inflated by one byte per line

There is deliberately no hashing tolerance for the old pattern: corrupted archives are fixed by repairing the files, not by special-case code.

## Repairing

A `repair --line-endings` command (with `--dry-run`) is planned -- see [#18] for its design and status.

Until it ships, the manual fix is a byte-level replacement of `\r\r\n` with `\r\n` in the affected `windowNN/tabNN.txt` files and `organized/` text files. The sequence cannot occur in files written by any editor, so the replacement is unambiguous. Do not rewrite through symlinks inside `organized/` -- repair the link target's session instead.

After repair, the next `compare` re-hashes the changed files automatically (the hash cache validates by mtime and size).

[#17]: https://github.com/DazzleTools/notepad-cleanup/issues/17
[#18]: https://github.com/DazzleTools/notepad-cleanup/issues/18
