"""Tiny read-only SQL helper for local debugging: python scripts/q.py DB "SQL; SQL" """
import sqlite3
import sys

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
for stmt in sys.argv[2].split(";"):
    if stmt.strip():
        print("--", stmt.strip()[:80])
        for r in con.execute(stmt):
            print("  ", r)
