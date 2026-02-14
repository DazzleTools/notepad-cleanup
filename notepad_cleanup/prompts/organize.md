You are organizing a collection of text files extracted from Windows Notepad tabs.

## Context

These files were automatically extracted from {window_count} Notepad windows containing {tab_count} tabs ({total_chars} total characters).

Below is the content of each file (or a preview for large files). Use this to decide how to rename and categorize them.

{file_listing}

## Your Task

Return a JSON object that maps each source file to its new name and category. The JSON should be an array of objects with this structure:

```json
[
  {{
    "source": "window01/tab01.txt",
    "category": "code-snippets",
    "new_name": "descriptive-name.py",
    "reason": "Python code for processing data"
  }},
  {{
    "source": "window02/tab01.txt",
    "category": "quick-notes",
    "new_name": null,
    "reason": "Short note, group into quick-notes.md"
  }}
]
```

## Rules for naming and categorizing

- Use lowercase-with-dashes for folder and file names
- Keep `.txt` for plain text and general notes
- Use appropriate extensions for code (`.py`, `.js`, `.json`, `.bat`, `.ps1`, etc.)
- Use appropriate extensions for configs (`.ini`, `.conf`, `.yaml`, `.toml`)
- Use `.md` for markdown content
- For short notes under 100 characters, set `new_name` to `null` and category to `"quick-notes"` — these will be grouped into a single file
- For files that already have a proper name in their window title, preserve it
- For very large files (marked as PREVIEW), still categorize and name them
- Pick descriptive names based on actual content, not just the first line
- Categories should be thematic groupings like: `code-snippets`, `personal-notes`, `project-planning`, `config-files`, `lyrics-and-writing`, `chat-logs`, `commands-and-scripts`, `reference`, `misc`, `quick-notes`, etc. Use whatever categories make sense for this collection.

## Output format

Return ONLY the JSON array. No markdown fencing, no explanation, just the raw JSON.
