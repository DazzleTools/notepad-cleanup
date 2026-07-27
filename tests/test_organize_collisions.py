"""Regression tests for organize plan validation and filename-collision safety.

Identifier legend
-----------------
Comments below cite short IDs that trace back to the project's design documents
(kept in the maintainers' private notes directory, referenced by filename only):

    GT-n  "Ground Truth" -- a measured, verified finding recorded during design.
          GT-10 is the defect this file guards against.
    AC-n  "Acceptance Check" -- a named condition the implementation is verified
          against. AC-22 (plan completeness) and AC-23 (collision safety) are
          the two this file implements.

Source documents:
    2026-07-25__14-07-53__editor-mode-architecture-and-sublime-archaeology.md
    2026-07-26__03-15-17__addendum__local-model-backend-and-collision-defect.md

The prose in each test states the condition in full, so the IDs are traceability
aids rather than required reading.

The defect (GT-10)
------------------

    execute_plan() computed `dest_path = cat_dir / new_name` with no existence
    check and used shutil.copy2(), which silently overwrites. Two plan entries
    sharing category + new_name produced ONE file on disk while stats["copied"]
    counted TWO and the summary reported both as organized successfully.

That is silent data loss with a success report. It is unacceptable in a pipeline
that ends in a drain (deleting the source session), because the drain's safety
argument is "verified extraction earns the right to delete."

Policy under test (AC-23): auto-rename and REPORT. Never silent, and never abort
a multi-batch run over a mere name clash -- the invariant is *no file is lost*,
not *no name is repeated*.
"""

import json
from pathlib import Path

import pytest

from notepad_cleanup import organizer


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _make_session(tmp_path, files):
    """Create a fake extraction dir. `files` maps relpath -> content."""
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def _organized_files(base_dir):
    """Every real (non-directory) file under organized/, as relpath -> content."""
    organized = Path(base_dir) / "organized"
    out = {}
    for p in organized.rglob("*"):
        if p.is_file() and p.name not in ("_summary.md", "_organized_links.json"):
            out[str(p.relative_to(organized)).replace("\\", "/")] = p.read_text(
                encoding="utf-8", errors="replace"
            )
    return out


# --------------------------------------------------------------------------
# AC-23 -- collision safety
# --------------------------------------------------------------------------

def test_colliding_names_do_not_lose_content(tmp_path):
    """THE REGRESSION: two distinct files given the same category+new_name.

    Both contents must survive on disk. Pre-fix, the second copy2() overwrote
    the first and only 'SECOND' remained.
    """
    base = _make_session(tmp_path, {
        "window01/tab01.txt": "FIRST",
        "window01/tab02.txt": "SECOND",
    })

    plan = [
        {"source": "window01/tab01.txt", "category": "notes",
         "new_name": "grocery-list.txt", "reason": "a list"},
        {"source": "window01/tab02.txt", "category": "notes",
         "new_name": "grocery-list.txt", "reason": "another list"},
    ]

    summary, stats = organizer.execute_plan(plan, base)
    found = _organized_files(base)

    # Two inputs -> two files on disk. This is the core invariant.
    assert len(found) == 2, (
        f"DATA LOSS: 2 plan entries produced {len(found)} file(s): {sorted(found)}"
    )

    # Both original contents must be present somewhere.
    assert sorted(found.values()) == ["FIRST", "SECOND"], (
        f"content lost or duplicated: {found}"
    )

    # Reported count must match reality -- no phantom successes.
    assert stats["copied"] == 2
    assert stats.get("errors", 0) == 0


def test_collision_rename_is_reported(tmp_path):
    """A rename must be visible in the summary -- never silent (AC-23)."""
    base = _make_session(tmp_path, {
        "window01/tab01.txt": "A",
        "window01/tab02.txt": "B",
        "window01/tab03.txt": "C",
    })
    plan = [
        {"source": f"window01/tab{i:02d}.txt", "category": "notes",
         "new_name": "same.txt", "reason": ""}
        for i in (1, 2, 3)
    ]

    summary, stats = organizer.execute_plan(plan, base)
    found = _organized_files(base)

    assert len(found) == 3, f"expected 3 files, got {sorted(found)}"

    # The two de-collided names must appear in the summary text so a human
    # reviewing _summary.md can see what was renamed and why.
    renamed = [n for n in found if n != "notes/same.txt"]
    assert len(renamed) == 2
    for name in renamed:
        leaf = Path(name).name
        assert leaf in summary, f"rename {leaf!r} not surfaced in summary"


def test_collision_across_categories_is_not_a_collision(tmp_path):
    """Same filename in DIFFERENT categories is legitimate -- must not rename."""
    base = _make_session(tmp_path, {
        "window01/tab01.txt": "code",
        "window01/tab02.txt": "note",
    })
    plan = [
        {"source": "window01/tab01.txt", "category": "code-snippets",
         "new_name": "readme.txt", "reason": ""},
        {"source": "window01/tab02.txt", "category": "personal-notes",
         "new_name": "readme.txt", "reason": ""},
    ]

    organizer.execute_plan(plan, base)
    found = _organized_files(base)

    assert set(found) == {"code-snippets/readme.txt", "personal-notes/readme.txt"}, (
        f"cross-category names were altered unnecessarily: {sorted(found)}"
    )


def test_extension_preserved_when_de_colliding(tmp_path):
    """De-collision must keep the extension so file type is not broken."""
    base = _make_session(tmp_path, {
        "window01/tab01.txt": "x = 1",
        "window01/tab02.txt": "y = 2",
    })
    plan = [
        {"source": "window01/tab01.txt", "category": "code",
         "new_name": "script.py", "reason": ""},
        {"source": "window01/tab02.txt", "category": "code",
         "new_name": "script.py", "reason": ""},
    ]

    organizer.execute_plan(plan, base)
    found = _organized_files(base)

    assert len(found) == 2
    assert all(n.endswith(".py") for n in found), (
        f"extension lost during de-collision: {sorted(found)}"
    )


def test_case_only_difference_collides_on_windows(tmp_path):
    """`Notes.txt` and `notes.txt` collide on a case-insensitive filesystem.

    De-collision keys on the lowercased path precisely so this is caught. Without
    it, the second copy2() would win on Windows and one file would be lost while
    both were reported as organized.
    """
    base = _make_session(tmp_path, {
        "window01/tab01.txt": "UPPER",
        "window01/tab02.txt": "lower",
    })
    plan = [
        {"source": "window01/tab01.txt", "category": "notes", "new_name": "Notes.txt"},
        {"source": "window01/tab02.txt", "category": "notes", "new_name": "notes.txt"},
    ]

    summary, stats = organizer.execute_plan(plan, base)
    found = _organized_files(base)

    assert len(found) == 2, f"case-only collision lost content: {sorted(found)}"
    assert sorted(found.values()) == ["UPPER", "lower"]
    assert stats["renamed"] == 1


def test_rename_counter_is_reported_in_stats(tmp_path):
    """stats['renamed'] must reflect reality so callers can gate on it."""
    base = _make_session(tmp_path, {
        "window01/tab01.txt": "A",
        "window01/tab02.txt": "B",
        "window01/tab03.txt": "C",
    })
    plan = [
        {"source": "window01/tab01.txt", "category": "x", "new_name": "n.txt"},
        {"source": "window01/tab02.txt", "category": "x", "new_name": "n.txt"},
        {"source": "window01/tab03.txt", "category": "x", "new_name": "other.txt"},
    ]
    summary, stats = organizer.execute_plan(plan, base)
    assert stats["renamed"] == 1
    assert stats["copied"] == 3


def test_rerun_does_not_accumulate_duplicates(tmp_path):
    """Idempotency guard: collisions are tracked per-run, not against disk.

    Checking the filesystem for existing files would make every re-run produce
    name-2, name-3, ... instead of overwriting its own prior output.
    """
    base = _make_session(tmp_path, {
        "window01/tab01.txt": "A",
        "window01/tab02.txt": "B",
    })
    plan = [
        {"source": "window01/tab01.txt", "category": "c", "new_name": "one.txt"},
        {"source": "window01/tab02.txt", "category": "c", "new_name": "two.txt"},
    ]

    organizer.execute_plan(plan, base)
    first = _organized_files(base)

    _, stats2 = organizer.execute_plan(plan, base)
    second = _organized_files(base)

    assert first == second, f"re-run changed the output: {first} -> {second}"
    assert stats2["renamed"] == 0, "re-run treated its own prior output as a collision"


def test_many_collisions_all_survive(tmp_path):
    """Batched backends can collide repeatedly; all content must survive."""
    n = 12
    base = _make_session(tmp_path, {
        f"window01/tab{i:02d}.txt": f"content-{i}" for i in range(1, n + 1)
    })
    plan = [
        {"source": f"window01/tab{i:02d}.txt", "category": "misc",
         "new_name": "clipboard-text.txt", "reason": ""}
        for i in range(1, n + 1)
    ]

    summary, stats = organizer.execute_plan(plan, base)
    found = _organized_files(base)

    assert len(found) == n, f"expected {n} files, got {len(found)}"
    assert sorted(found.values()) == sorted(f"content-{i}" for i in range(1, n + 1))
    assert stats["copied"] == n


# --------------------------------------------------------------------------
# AC-22 -- plan completeness
# --------------------------------------------------------------------------

def test_validate_plan_flags_duplicate_sources(tmp_path):
    """A source appearing twice is a backend bug -- must be detected (AC-22)."""
    base = _make_session(tmp_path, {"window01/tab01.txt": "A"})
    plan = [
        {"source": "window01/tab01.txt", "category": "a", "new_name": "x.txt"},
        {"source": "window01/tab01.txt", "category": "b", "new_name": "y.txt"},
    ]
    problems = organizer.validate_plan(plan, base)
    assert any("duplicate" in p.lower() for p in problems), problems


def test_validate_plan_flags_missing_sources(tmp_path):
    """Every extracted file must appear in the plan exactly once (AC-22).

    This is the gate protecting the drain: a file absent from the plan would be
    unorganized, and a later drain would delete its only copy.
    """
    base = _make_session(tmp_path, {
        "window01/tab01.txt": "A",
        "window01/tab02.txt": "B",
    })
    plan = [{"source": "window01/tab01.txt", "category": "a", "new_name": "x.txt"}]

    problems = organizer.validate_plan(plan, base, expected_sources=[
        "window01/tab01.txt", "window01/tab02.txt",
    ])
    assert any("tab02" in p for p in problems), problems


def test_validate_plan_flags_nonexistent_source(tmp_path):
    """A hallucinated filename must be caught before execution."""
    base = _make_session(tmp_path, {"window01/tab01.txt": "A"})
    plan = [
        {"source": "window01/tab01.txt", "category": "a", "new_name": "x.txt"},
        {"source": "window01/tab99.txt", "category": "a", "new_name": "y.txt"},
    ]
    problems = organizer.validate_plan(plan, base)
    assert any("tab99" in p for p in problems), problems


def test_validate_plan_accepts_a_clean_plan(tmp_path):
    """A correct plan must produce no complaints."""
    base = _make_session(tmp_path, {
        "window01/tab01.txt": "A",
        "window01/tab02.txt": "B",
    })
    plan = [
        {"source": "window01/tab01.txt", "category": "a", "new_name": "x.txt"},
        {"source": "window01/tab02.txt", "category": "b", "new_name": "y.txt"},
    ]
    problems = organizer.validate_plan(plan, base, expected_sources=[
        "window01/tab01.txt", "window01/tab02.txt",
    ])
    assert problems == [], problems


# --------------------------------------------------------------------------
# no-regression on existing behaviour
# --------------------------------------------------------------------------

def test_normal_plan_still_works(tmp_path):
    """The ordinary non-colliding path must be unchanged."""
    base = _make_session(tmp_path, {
        "window01/tab01.txt": "print('hi')",
        "window02/tab01.txt": "milk, eggs",
    })
    plan = [
        {"source": "window01/tab01.txt", "category": "code-snippets",
         "new_name": "hello.py", "reason": "python"},
        {"source": "window02/tab01.txt", "category": "personal-notes",
         "new_name": "shopping.txt", "reason": "list"},
    ]

    summary, stats = organizer.execute_plan(plan, base)
    found = _organized_files(base)

    assert found == {
        "code-snippets/hello.py": "print('hi')",
        "personal-notes/shopping.txt": "milk, eggs",
    }
    assert stats["copied"] == 2
    assert stats["errors"] == 0
    assert (Path(base) / "organized" / "_summary.md").exists()


def test_missing_source_still_counts_as_error(tmp_path):
    """Pre-existing behaviour: a missing source increments errors, not copies."""
    base = _make_session(tmp_path, {"window01/tab01.txt": "A"})
    plan = [
        {"source": "window01/tab01.txt", "category": "a", "new_name": "x.txt"},
        {"source": "window09/tab09.txt", "category": "a", "new_name": "y.txt"},
    ]
    summary, stats = organizer.execute_plan(plan, base)
    assert stats["copied"] == 1
    assert stats["errors"] == 1
