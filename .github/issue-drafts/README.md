# Issue Drafts

This folder is the **drop-zone for agent-created GitHub issues**.

Drop a Markdown file here with YAML frontmatter, push it, and the
`Create Issue from Draft` GitHub Actions workflow automatically opens the
corresponding issue on GitHub — no PAT, no extra tokens, no manual steps.

---

## File format

```markdown
---
title: "Your issue title"
labels: enhancement, feature
---

## Summary

Issue body in normal Markdown…
```

The only required frontmatter field is `title`. `labels` is a comma-separated
list; any label that doesn't exist in the repo is silently skipped.

---

## How it works

```
Agent writes draft file → git push → GitHub Actions workflow fires →
  gh issue create (using built-in GITHUB_TOKEN) → issue appears
```

The workflow (`create-issue-from-draft.yml`) runs on `push` events that touch
this directory. It uses the **built-in `GITHUB_TOKEN`** with `permissions:
issues: write` declared in the workflow — no PAT or external secret needed.

---

## One-time setup (repo owner action required)

**Why does the first run say `action_required`?**

GitHub's security model holds any workflow run where the workflow file itself
is new (i.e., not yet on the default branch). This prevents a malicious PR from
running arbitrary Actions code before a maintainer reviews it. The token and
permissions are correct; the job just hasn't started yet.

**Fix — do this once:**

1. **Merge the PR** that introduced `create-issue-from-draft.yml` into `main`.
   That's all. Once the workflow file lives on `main`, every future push that
   adds a draft file here will fire the workflow immediately — no approval
   needed, no PAT needed.

2. *(Optional)* Confirm that Actions write permissions are not globally
   disabled for the repo:
   `Settings → Actions → General → Workflow permissions`
   → select **"Read and write permissions"** (or leave the default if it's
   already "Read and write").

After step 1 there is nothing else to configure. The `GITHUB_TOKEN` that
GitHub Actions injects automatically is fully sufficient.

---

## Why no PAT is needed

| Where the code runs | Token available | Can write issues? |
|---|---|---|
| Agent sandbox | `GITHUB_TOKEN` (read-only clone token) | ✗ |
| GitHub Actions job | `secrets.GITHUB_TOKEN` (full repo token) | ✓ (with `issues: write`) |

The agent sandbox token is intentionally read-only. Rather than adding a
separate secret, this workflow delegates the write operation to GitHub Actions,
which already has the right token in every run.

---

## Adding a new issue (agent workflow)

1. Create a `.md` file in this folder with the frontmatter above.
2. Push the branch (via `report_progress`).
3. The workflow fires and the issue is created automatically.

Each file is processed only once: the workflow uses `git diff --diff-filter=A`
to detect newly *added* files, so editing an existing draft won't re-open a
duplicate issue.

---

## Running manually (optional)

```bash
# From the repo root, with gh CLI authenticated:
python scripts/create_issue_from_draft.py .github/issue-drafts/my-issue.md
```
