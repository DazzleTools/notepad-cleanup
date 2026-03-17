You are organizing a collection of text files extracted from Windows Notepad tabs.

## Context

These files were automatically extracted from {window_count} Notepad windows containing {tab_count} tabs ({total_chars} total characters). The files are in the current working directory.

Each `windowNN/` folder corresponds to one Notepad window. Each `tabNN.txt` is one tab's content. The `manifest.json` contains metadata about every file including content type hints and tab labels.
{skip_section}
{reference_section}
## Your Task

1. Read `manifest.json` to understand the full collection
2. Read each tab file to understand its content. To save time:
   - For small files (<1KB), the manifest label and content type hint may be enough — read only if unclear
   - For medium files (1-10KB), read the first ~50 lines to get the gist
   - For large files (>10KB), read the first ~50 lines and optionally grep for key sections
   - For very large files (>50KB), just use the manifest metadata — don't read the file
3. Return a JSON plan for how to organize the files

## JSON Output Format

Return ONLY a JSON array. No markdown fencing, no explanation, just raw JSON:

[
  {{
    "source": "window01/tab01.txt",
    "category": "code-snippets",
    "new_name": "descriptive-name.py",
    "reason": "Python code for processing data"
  }},
  {{
    "source": "window02/tab01.txt",
    "category": "personal-notes",
    "new_name": "quick-reminder-about-groceries.txt",
    "reason": "Short personal note"
  }}
]

## Rules for naming and categorizing

- Every file MUST get its own `new_name` — never set it to null
- Each tab is preserved as an individual file, even short notes
- Use lowercase-with-dashes for folder and file names
- Keep `.txt` for plain text and general notes
- Use appropriate extensions for code (`.py`, `.js`, `.json`, `.bat`, `.ps1`, etc.)
- Use appropriate extensions for configs (`.ini`, `.conf`, `.yaml`, `.toml`)
- Use `.md` for markdown content
- For files that already have a proper name in their window title, preserve it
- Pick descriptive names based on actual content, not just the first line
- Categories should be thematic groupings like: `code-snippets`, `personal-notes`, `project-planning`, `config-files`, `lyrics-and-writing`, `chat-logs`, `commands-and-scripts`, `reference`, `misc`, etc. Use whatever categories make sense for this collection.
- NEVER modify or delete the original files — you are only producing a JSON plan
