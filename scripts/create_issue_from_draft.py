#!/usr/bin/env python3
"""Create a GitHub issue from a markdown draft file with YAML frontmatter.

File format (.github/issue-drafts/my-issue.md):

    ---
    title: "My Issue Title"
    labels: enhancement, feature
    ---

    ## Summary
    ...markdown body...

Usage:
    python scripts/create_issue_from_draft.py .github/issue-drafts/my-issue.md
    python scripts/create_issue_from_draft.py my-issue.md --repo owner/repo

Requires:
    gh CLI authenticated with issues:write permission (automatically satisfied
    inside GitHub Actions via the built-in GITHUB_TOKEN).

NOTE — action_required / no PAT needed:
    The GitHub Actions workflow that calls this script uses the built-in
    GITHUB_TOKEN with `permissions: issues: write`.  No PAT is required.
    If the workflow shows `action_required`, merge the PR that introduced
    create-issue-from-draft.yml to main — GitHub only holds the *first* run
    of a brand-new workflow file.  Subsequent runs fire automatically.
"""

import os
import re
import subprocess
import sys
import tempfile
from argparse import ArgumentParser
from pathlib import Path


def parse_draft(path):
    """Parse a draft file into (metadata dict, body string).

    Returns metadata with keys:
        title  (str)
        labels (list[str])
    """
    content = Path(path).read_text(encoding="utf-8")

    match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    if not match:
        # No frontmatter — derive title from filename
        stem = Path(path).stem.replace("-", " ").replace("_", " ").title()
        return {"title": stem, "labels": []}, content.strip()

    frontmatter_text = match.group(1)
    body = match.group(2).strip()

    metadata = {}
    for line in frontmatter_text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip().strip("\"'")

    labels_raw = metadata.get("labels", "")
    metadata["labels"] = [lbl.strip() for lbl in labels_raw.split(",") if lbl.strip()]

    return metadata, body


def create_issue(title, body, labels, repo=None):
    """Call gh issue create and return the new issue URL.

    Args:
        title:  Issue title string.
        body:   Issue body markdown string.
        labels: List of label name strings (may be empty).
        repo:   Optional "owner/repo" string passed to gh via --repo.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(body)
        tmp_path = tf.name

    try:
        cmd = ["gh", "issue", "create", "--title", title, "--body-file", tmp_path]
        if repo:
            cmd += ["--repo", repo]
        for label in labels:
            cmd += ["--label", label]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()

        # Labels might not exist — retry without them
        if labels and "could not find label" in result.stderr.lower():
            print(f"  Warning: one or more labels not found; retrying without labels.")
            cmd_no_labels = [
                "gh", "issue", "create",
                "--title", title,
                "--body-file", tmp_path,
            ]
            if repo:
                cmd_no_labels += ["--repo", repo]
            result2 = subprocess.run(cmd_no_labels, capture_output=True, text=True)
            if result2.returncode == 0:
                return result2.stdout.strip()
            raise RuntimeError(result2.stderr.strip())

        raise RuntimeError(result.stderr.strip())
    finally:
        os.unlink(tmp_path)


def main():
    parser = ArgumentParser(
        description="Create a GitHub issue from a Markdown draft file with YAML frontmatter.",
        epilog=(
            "Examples:\n"
            "  python scripts/create_issue_from_draft.py .github/issue-drafts/my-issue.md\n"
            "  python scripts/create_issue_from_draft.py my-issue.md --repo owner/repo"
        ),
    )
    parser.add_argument("draft", metavar="draft_file.md",
                        help="Path to the draft Markdown file")
    parser.add_argument("--repo", metavar="owner/repo",
                        help="Target repository (default: inferred from gh CLI context)")
    args = parser.parse_args()

    if not Path(args.draft).exists():
        parser.error(f"file not found: {args.draft}")

    metadata, body = parse_draft(args.draft)
    title = metadata.get("title") or Path(args.draft).stem
    labels = metadata.get("labels", [])

    print(f"Title:  {title}")
    if labels:
        print(f"Labels: {', '.join(labels)}")
    if args.repo:
        print(f"Repo:   {args.repo}")

    try:
        url = create_issue(title, body, labels, repo=args.repo)
        print(f"Issue created: {url}")
    except RuntimeError as exc:
        print(f"Error creating issue: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
