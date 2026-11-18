"""Commits, lines and files changed per author, for report Section 10 (Contribution).

    python scripts/git_author_stats.py                 # whole history, Markdown table
    python scripts/git_author_stats.py --files         # also list the files each author touched
    python scripts/git_author_stats.py --since 2026-10-15 --csv > contrib.csv

Authors are grouped by e-mail, so commits from the same person under two
names count once.  Merge commits are skipped (they are not original work).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import defaultdict


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        sys.exit(f"git failed: {exc}. Run this inside the repository.")


def collect(since: str | None):
    if subprocess.run(["git", "rev-parse", "--verify", "HEAD"], capture_output=True).returncode != 0:
        return {}
    cmd = ["log", "--no-merges", "--numstat", "--format=@@%H%x09%an%x09%ae%x09%ad", "--date=short"]
    if since:
        cmd.append(f"--since={since}")
    stats = defaultdict(lambda: {"names": set(), "commits": 0, "added": 0, "deleted": 0,
                                 "files": defaultdict(int), "first": None, "last": None})
    who = None
    for line in git(*cmd).splitlines():
        if line.startswith("@@"):
            _, name, email, date = line[2:].split("\t")
            who = stats[email.lower()]
            who["names"].add(name)
            who["commits"] += 1
            who["first"] = date if who["first"] is None or date < who["first"] else who["first"]
            who["last"] = date if who["last"] is None or date > who["last"] else who["last"]
        elif line.strip() and who is not None:
            add, dele, path = line.split("\t", 2)
            if add != "-":                      # "-" = binary file
                who["added"] += int(add)
                who["deleted"] += int(dele)
            who["files"][path] += 1
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", help="only commits after this date (YYYY-MM-DD)")
    ap.add_argument("--files", action="store_true", help="list files per author")
    ap.add_argument("--csv", action="store_true", help="CSV instead of Markdown")
    a = ap.parse_args()
    stats = collect(a.since)
    if not stats:
        print("No commits yet.")
        return
    rows = sorted(stats.items(), key=lambda kv: -kv[1]["commits"])
    if a.csv:
        print("author,email,commits,files_changed,lines_added,lines_deleted,first,last")
        for email, s in rows:
            print(f"{'/'.join(sorted(s['names']))},{email},{s['commits']},{len(s['files'])},"
                  f"{s['added']},{s['deleted']},{s['first']},{s['last']}")
        return
    print("| Author | Commits | Files changed | Lines + / - | First | Last |")
    print("|---|---|---|---|---|---|")
    for email, s in rows:
        print(f"| {' / '.join(sorted(s['names']))} | {s['commits']} | {len(s['files'])} | "
              f"+{s['added']} / -{s['deleted']} | {s['first']} | {s['last']} |")
    if a.files:
        for email, s in rows:
            print(f"\n### {' / '.join(sorted(s['names']))}")
            for path, n in sorted(s["files"].items(), key=lambda kv: (-kv[1], kv[0])):
                print(f"- {path} ({n} commit{'s' if n > 1 else ''})")


if __name__ == "__main__":
    main()
