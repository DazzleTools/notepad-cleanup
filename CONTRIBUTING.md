# Contributing to notepad-cleanup

Thank you for considering contributing to notepad-cleanup!

## How Can I Contribute?

### Reporting Bugs

Before submitting a bug report:
- Check existing issues to see if the problem has already been reported
- Verify you're using the latest version
- Ensure you're running Windows 11 with Python 3.10+

When submitting a bug report, include:
- The exact command you ran
- Full error message and stack trace
- Your environment details (OS version, Python version, installation method)
- Number of Notepad windows/tabs involved
- Any relevant console output

Use the bug report template in the Issues section.

### Suggesting Enhancements

Enhancement suggestions are welcome! When suggesting a feature:
- Explain the use case clearly
- Describe the expected behavior
- Consider how it fits with the existing workflow (extract → organize)
- Mention any alternatives you've considered

Use the feature request template in the Issues section.

### Pull Requests

Pull requests are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-improvement`)
3. Make your changes following the code style
4. Test on Windows 11 with actual Notepad windows
5. Update documentation if needed
6. Commit with clear messages (no attribution required)
7. Push to your fork
8. Submit a pull request

#### Code Style
- Follow PEP 8 for Python code
- Use type hints where appropriate
- Add docstrings to new functions
- Keep functions focused and single-purpose
- Use descriptive variable names

#### Testing
Test your changes manually:
- Create multiple Notepad windows with various tab counts
- Test with empty tabs, large tabs, special characters
- Verify extraction accuracy
- Check organization output (if modifying organizer.py)

## Development Setup

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install in development mode
pip install -e .

# Run the tool
notepad-cleanup extract
notepad-cleanup organize "path\to\output"
```

## Project Structure

```
notepad_cleanup/
├── cli.py          # Click-based CLI entry point
├── discovery.py    # Window enumeration
├── extractor.py    # Two-phase text extraction
├── organizer.py    # Claude Code integration
├── saver.py        # File output and manifest
└── prompts/        # AI prompt templates
```

## Questions?

Open a discussion in the repository or reach out to @djdarcy.
