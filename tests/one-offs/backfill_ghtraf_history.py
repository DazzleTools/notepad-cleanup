"""
Backfill ghtraf dailyHistory from GitHub's 14-day traffic API window.

The traffic-badges workflow only captures data from the day it starts running.
This script seeds historical entries from GitHub's clone/view traffic API
(which retains 14 days) so the dashboard shows the full available history.

Usage:
    python tests/one-offs/backfill_ghtraf_history.py
    python tests/one-offs/backfill_ghtraf_history.py --dry-run
    python tests/one-offs/backfill_ghtraf_history.py --gist-id XXXX --owner OWNER --repo REPO

Requires: gh CLI authenticated with gist access.
"""

import argparse
import json
import subprocess
import sys


def run_gh(args):
    result = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: gh {' '.join(args)}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Backfill ghtraf dailyHistory from GitHub traffic API"
    )
    parser.add_argument("--gist-id", default=None,
                        help="Badge gist ID (reads from .ghtraf.json if not set)")
    parser.add_argument("--owner", default=None,
                        help="GitHub repo owner (reads from .ghtraf.json if not set)")
    parser.add_argument("--repo", default=None,
                        help="GitHub repo name (reads from .ghtraf.json if not set)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing to gist")
    args = parser.parse_args()

    # Try reading from .ghtraf.json if args not provided
    gist_id = args.gist_id
    owner = args.owner
    repo = args.repo

    if not all([gist_id, owner, repo]):
        try:
            with open(".ghtraf.json", encoding="utf-8") as f:
                config = json.load(f)
            gist_id = gist_id or config.get("badge_gist_id")
            owner = owner or config.get("owner")
            repo = repo or config.get("repo")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    if not all([gist_id, owner, repo]):
        print("ERROR: Provide --gist-id, --owner, --repo or run from a directory with .ghtraf.json",
              file=sys.stderr)
        sys.exit(1)

    print(f"Gist:  {gist_id}")
    print(f"Repo:  {owner}/{repo}")
    print()

    # Get current state from gist
    print("Fetching gist state.json...")
    state_raw = run_gh(["api", f"gists/{gist_id}", "--jq", '.files["state.json"].content'])
    state = json.loads(state_raw)

    existing = {e["date"] for e in state.get("dailyHistory", [])}
    print(f"  Existing dailyHistory entries: {len(existing)}")

    # Get traffic data from GitHub API
    print("Fetching clone traffic (14-day window)...")
    clones_data = json.loads(run_gh(["api", f"repos/{owner}/{repo}/traffic/clones"]))

    print("Fetching view traffic (14-day window)...")
    views_data = json.loads(run_gh(["api", f"repos/{owner}/{repo}/traffic/views"]))

    clone_by_date = {c["timestamp"]: c for c in clones_data.get("clones", [])}
    view_by_date = {v["timestamp"]: v for v in views_data.get("views", [])}

    print(f"  Clone data: {len(clone_by_date)} days, {clones_data.get('count', 0)} total, {clones_data.get('uniques', 0)} unique")
    print(f"  View data:  {len(view_by_date)} days, {views_data.get('count', 0)} total, {views_data.get('uniques', 0)} unique")

    # Build missing entries
    all_dates = sorted(set(list(clone_by_date.keys()) + list(view_by_date.keys())))
    added = 0

    for date in all_dates:
        if date in existing:
            continue

        c = clone_by_date.get(date, {})
        v = view_by_date.get(date, {})

        entry = {
            "date": date,
            "capturedAt": date,
            "clones": c.get("count", 0),
            "downloads": 0,
            "views": v.get("count", 0),
            "total": c.get("count", 0) + v.get("count", 0),
            "ciCheckouts": 0,
            "organicClones": c.get("count", 0),
            "stars": 0,
            "forks": 0,
            "openIssues": 0,
            "uniqueClones": c.get("uniques", 0),
            "uniqueViews": v.get("uniques", 0),
            "ciRuns": 0,
            "organicUniqueClones": c.get("uniques", 0),
        }
        state["dailyHistory"].append(entry)
        added += 1
        print(f"  + {date[:10]}: {c.get('count', 0)} clones, {v.get('count', 0)} views")

    # Sort by date
    state["dailyHistory"].sort(key=lambda x: x["date"])

    # Update trackingSince
    if state["dailyHistory"]:
        state["trackingSince"] = state["dailyHistory"][0]["date"]

    print(f"\nAdded {added} historical entries")
    print(f"Total dailyHistory: {len(state['dailyHistory'])} entries")
    print(f"Tracking since: {state.get('trackingSince', 'unknown')}")

    if args.dry_run:
        print("\n[DRY RUN] No changes written.")
        return

    # Write back to gist
    print("\nUpdating gist...")
    state_json = json.dumps(state, indent=2)
    result = subprocess.run(
        ["gh", "gist", "edit", gist_id, "-f", "state.json", "-"],
        input=state_json, capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("Done!")
    else:
        print(f"ERROR: {result.stderr}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
