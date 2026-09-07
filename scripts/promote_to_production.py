"""Regenerate the production branch from develop.

    python scripts/promote_to_production.py --dry-run
    python scripts/promote_to_production.py

Production is not merged into -- it is rebuilt. Take develop's tree, drop
everything in EXCLUDE, lay OVERLAY_DIR over the result, commit that to
`production`.

The reason is that production is a strict subset of develop: the same code,
minus the benchmark, the question sets, the result archives and the registry
sources. A merge would keep reintroducing exactly what the branch exists to
exclude, and resolving that by hand every release is a job nobody does
correctly twice. Regenerating cannot drift: the exclusion list below is the
only definition of what production is, so a new development artifact is kept
out of production by adding one line to it.

Two files genuinely differ rather than being absent, and those live in
promotion/overlay/ mirroring their real paths. Keep that set as small as
possible -- an overlaid file has to be updated in two places forever. It is
almost always better to make the shared file tolerate production's absences
(as ui/app.js does for a missing mock.js) than to add an overlay.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY_DIR = ROOT / "promotion" / "overlay"

SOURCE_BRANCH = "develop"
TARGET_BRANCH = "production"

# Everything here is development-only. Paths are repo-relative; a directory
# takes its whole subtree. Grouped by why it is excluded, because "why" is
# what a reader needs when deciding where a new file belongs.
EXCLUDE = [
    # -- Retired demo database. Superseded by the real tms_* views: schema.sql
    #    creates users/workflows/tasks, which metadata/schema_description.yaml
    #    no longer describes and no query targets.
    "database/schema.sql",
    "database/seed.sql",
    "database/setup.py",
    "scripts/setup_demo.py",
    "tests/test_database.py",

    # -- The benchmark: question sets, ground truth, scoring, reporting.
    "benchmark",
    "results",
    "scripts/run_benchmark.py",
    "scripts/run_lean_suite.py",
    "scripts/run_single.py",
    "scripts/rescore.py",
    "scripts/semantic_rescore.py",
    "scripts/analyze_followup.py",
    "scripts/analyze_lean.py",
    "scripts/verify_ground_truth.py",
    "tests/test_classify.py",
    "tests/test_ground_truth.py",
    "tests/test_lean_suite.py",
    "tests/test_metadata.py",
    "tests/test_report.py",

    # -- Source datasets. metadata/*.yaml is generated from these and promoted
    #    as output; the sources themselves are not deployed.
    "TMS_Semantic_Registry_v2 (1)",
    "TMS_Semantic_Registry_Learning_Material (1)",
    "TMS_AI_Golden_Challenge_Test_Set (1).csv",

    # -- Generators and setup tooling for the above. Dropping build_wren.py and
    #    check_environment.py orphans three wren_setup modules, so they go too;
    #    mcp_config.py stays because serve_api.py and cli_provider.py import it.
    "scripts/build_gazetteer.py",
    "scripts/build_schema_description.py",
    "scripts/build_expansion_suite.py",
    "scripts/build_followup_suite.py",
    "scripts/build_targeted_suite.py",
    "scripts/build_wren.py",
    "scripts/check_environment.py",
    "wren_setup/build.py",
    "wren_setup/helpers.py",
    "wren_setup/preflight.py",

    # -- Documentation of work rather than of the system.
    "docs/followup-layer-report.md",
    "docs/scalable_text_to_sql_architecture.md",
    "docs/v2-chat-context.md",
    "docs/wren-findings.md",
    "docs/data-flow.md",          # a captured trace; cites scripts/run_single.py
    "docs/superpowers",

    # -- Fixtures, editor droppings, other agents' instruction files.
    "ui/mock.js",
    "claude/.cph",
    "gemini.md",

    # -- This machinery. It rebuilds production; it does not ship to it.
    "promotion",
    "scripts/promote_to_production.py",
]


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                       text=True, check=False)
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def preflight() -> None:
    if git("status", "--porcelain"):
        raise SystemExit(
            "Working tree is not clean. Promotion copies the committed tree of "
            f"{SOURCE_BRANCH}, so uncommitted work would be silently omitted.\n"
            "Commit or stash first."
        )
    if git("rev-parse", "--abbrev-ref", "HEAD") != SOURCE_BRANCH:
        raise SystemExit(f"Run this from {SOURCE_BRANCH}.")

    missing = [p for p in EXCLUDE if not (ROOT / p).exists()]
    if missing:
        # A path that no longer exists is usually a rename nobody updated here,
        # which would silently start shipping something to production.
        raise SystemExit(
            "These EXCLUDE entries do not exist on "
            f"{SOURCE_BRANCH} -- renamed or deleted?\n  "
            + "\n  ".join(missing)
        )


def build_tree(dest: Path) -> tuple[list[str], list[str]]:
    """Lay down develop's committed tree, minus EXCLUDE, plus the overlay."""
    files = git("ls-tree", "-r", "--name-only", SOURCE_BRANCH).splitlines()

    excluded, kept = [], []
    for f in files:
        if any(f == e or f.startswith(e + "/") for e in EXCLUDE):
            excluded.append(f)
        else:
            kept.append(f)

    for f in kept:
        target = dest / f
        target.parent.mkdir(parents=True, exist_ok=True)
        blob = subprocess.run(["git", "show", f"{SOURCE_BRANCH}:{f}"],
                              cwd=ROOT, capture_output=True, check=True)
        target.write_bytes(blob.stdout)

    overlaid = []
    for src in sorted(OVERLAY_DIR.rglob("*")):
        if src.is_file():
            rel = src.relative_to(OVERLAY_DIR).as_posix()
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest / rel)
            overlaid.append(rel)

    return kept, overlaid


def prune_emptied_dirs() -> list[str]:
    """Remove directories the promotion emptied.

    Switching branches in place leaves the husks behind -- git does not track
    directories, so `benchmark/` and the registry folders survive as empty
    shells and a production checkout still looks like it contains them.

    A directory holding only __pycache__ counts as empty: those are compiled
    copies of modules that no longer exist on this branch, and a stale one can
    shadow a real import. Anything else is left alone, which is what keeps
    results/ and wren_projects/ -- gitignored, but real data -- intact.
    """
    removed = []
    protected = {".git", ".venv"}

    for path in sorted((p for p in ROOT.rglob("*") if p.is_dir()),
                       key=lambda p: len(p.parts), reverse=True):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in protected:
            continue
        if path.name == "__pycache__":
            shutil.rmtree(path, ignore_errors=True)
            continue
        if not any(path.iterdir()):
            path.rmdir()
            removed.append(rel.as_posix())

    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be promoted, change nothing")
    ap.add_argument("-m", "--message",
                    help="commit message (default names the source commit)")
    args = ap.parse_args()

    preflight()
    source_sha = git("rev-parse", "--short", SOURCE_BRANCH)

    with tempfile.TemporaryDirectory(prefix="promote-") as tmp:
        staging = Path(tmp) / "tree"
        staging.mkdir()
        kept, overlaid = build_tree(staging)

        print(f"{SOURCE_BRANCH} @ {source_sha}")
        print(f"  {len(kept)} file(s) promoted")
        print(f"  {len(overlaid)} overlaid: {', '.join(overlaid) or 'none'}")

        if args.dry_run:
            print("\nwould promote:")
            for f in kept:
                print(f"  {f}")
            return 0

        exists = git("rev-parse", "--verify", "--quiet",
                     f"refs/heads/{TARGET_BRANCH}", check=False)
        if exists:
            git("checkout", "-q", TARGET_BRANCH)
        else:
            # Branched from develop rather than orphaned, so the two share a
            # history and `git diff develop production` reads as the exclusion
            # list rather than as every file in the repository.
            git("checkout", "-q", "-b", TARGET_BRANCH, SOURCE_BRANCH)

        # Clear the branch's tracked files, then write the new tree. Anything
        # dropped from EXCLUDE's complement disappears rather than lingering.
        for f in git("ls-files").splitlines():
            (ROOT / f).unlink(missing_ok=True)

        for src in sorted(staging.rglob("*")):
            if src.is_file():
                rel = src.relative_to(staging)
                (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, ROOT / rel)

        pruned = prune_emptied_dirs()
        if pruned:
            print(f"  {len(pruned)} emptied dir(s) removed: "
                  + ", ".join(pruned[:6]) + ("..." if len(pruned) > 6 else ""))

        git("add", "-A")
        if not git("status", "--porcelain"):
            print(f"\n{TARGET_BRANCH} already matches {SOURCE_BRANCH} @ {source_sha}")
            return 0

        message = args.message or (
            f"Promote {SOURCE_BRANCH} {source_sha} to {TARGET_BRANCH}\n\n"
            f"Generated by scripts/promote_to_production.py. "
            f"{len(kept)} file(s) from {SOURCE_BRANCH}, "
            f"{len(overlaid)} overlaid from promotion/overlay/."
        )
        git("commit", "-q", "-m", message)
        print(f"\n{TARGET_BRANCH} @ {git('rev-parse', '--short', 'HEAD')}")
        print(f"  git checkout {SOURCE_BRANCH}   # back to development")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
