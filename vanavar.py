#!/usr/bin/env python3
"""
vanavar - associative memory

Store any line, find it by any term (prefix match by default).
Supports offline use with sync to shared database.
    > VSNT reporter "Alex Sherman" alex.sherman@versantmedia.com @sherman4949
    > find alex
    > find VSNT
    > sync /path/to/shared.db
"""

import sqlite3
import os
import uuid as uuid_lib
from pathlib import Path
from datetime import datetime

try:
    import readline
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False

# Use VANAVAR_DB env var if set, otherwise local
DB_PATH = Path(os.environ.get('VANAVAR_DB', Path(__file__).parent / "vanavar.db"))


def input_with_prefill(prompt, prefill=''):
    """
    Edit with prefill. Options:
    - Enter: keep original
    - +text: append text to original
    - text: replace with text
    """
    print(f"Current: {prefill}")
    result = input(f"{prompt}(Enter=keep, +text=append, or replace): ").strip()
    if not result:
        return prefill
    elif result.startswith('+'):
        return prefill + ' ' + result[1:].strip()
    else:
        return result


def init_db(db_path=None):
    """Initialize database, migrating if needed."""
    if db_path is None:
        db_path = DB_PATH
    conn = sqlite3.connect(db_path)

    # Check if we need to migrate (old schema without uuid)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='entries'")
    table_exists = cur.fetchone() is not None

    if table_exists:
        # Check if uuid column exists by looking at table info
        cur = conn.execute("PRAGMA table_info(entries)")
        columns = [row[1] for row in cur.fetchall()]

        if 'uuid' not in columns:
            # Migrate: backup data, drop table, recreate with uuid
            print("Migrating database to add UUID support...")
            cur = conn.execute("SELECT content, created_at FROM entries")
            old_entries = cur.fetchall()
            conn.execute("DROP TABLE entries")
            conn.execute("""
                CREATE VIRTUAL TABLE entries USING fts5(
                    content,
                    uuid UNINDEXED,
                    created_at UNINDEXED
                )
            """)
            for content, created_at in old_entries:
                conn.execute(
                    "INSERT INTO entries (content, uuid, created_at) VALUES (?, ?, ?)",
                    (content, str(uuid_lib.uuid4()), created_at)
                )
            conn.commit()
            print(f"Migrated {len(old_entries)} entries.")
    else:
        # Create new table with uuid
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS entries USING fts5(
                content,
                uuid UNINDEXED,
                created_at UNINDEXED
            )
        """)
        conn.commit()

    return conn


def store(conn, text):
    """Store a line with a new UUID."""
    conn.execute(
        "INSERT INTO entries (content, uuid, created_at) VALUES (?, ?, ?)",
        (text, str(uuid_lib.uuid4()), datetime.now().isoformat())
    )
    conn.commit()


def find(conn, term, prefix=True):
    """Find entries matching a term. Prefix match by default."""
    escaped = term.replace('"', '""')
    if prefix and not term.endswith('$'):
        query = f'"{escaped}"*'  # prefix match
    else:
        # Exact match (user ended with $ to indicate exact)
        query = f'"{escaped.rstrip("$")}"'
    cur = conn.execute(
        'SELECT rowid, content FROM entries WHERE entries MATCH ?',
        (query,)
    )
    return [(row[0], row[1]) for row in cur.fetchall()]


def find_all(conn, terms, prefix=True):
    """Find entries matching ALL terms."""
    parts = []
    for t in terms:
        escaped = t.replace('"', '""')
        if prefix and not t.endswith('$'):
            parts.append(f'"{escaped}"*')
        else:
            parts.append(f'"{escaped.rstrip("$")}"')
    query = ' '.join(parts)
    cur = conn.execute(
        'SELECT rowid, content FROM entries WHERE entries MATCH ?',
        (query,)
    )
    return [(row[0], row[1]) for row in cur.fetchall()]


def list_all(conn, limit=50):
    """List recent entries."""
    cur = conn.execute(
        "SELECT rowid, content FROM entries ORDER BY created_at DESC LIMIT ?",
        (limit,)
    )
    return [(row[0], row[1]) for row in cur.fetchall()]


def delete_by_id(conn, rowid):
    """Delete entry by rowid."""
    conn.execute('DELETE FROM entries WHERE rowid = ?', (rowid,))
    conn.commit()


def delete_by_term(conn, term):
    """Delete entries matching a term."""
    escaped = term.replace('"', '""')
    cur = conn.execute(
        'DELETE FROM entries WHERE entries MATCH ?',
        (f'"{escaped}"*',)
    )
    conn.commit()
    return cur.rowcount


def update_entry(conn, rowid, new_content):
    """Update an entry's content."""
    conn.execute(
        'UPDATE entries SET content = ? WHERE rowid = ?',
        (new_content, rowid)
    )
    conn.commit()


def count(conn):
    """Count total entries."""
    cur = conn.execute("SELECT COUNT(*) FROM entries")
    return cur.fetchone()[0]


def export_entries(conn, filepath):
    """Export all entries to a file."""
    cur = conn.execute("SELECT content FROM entries ORDER BY created_at")
    with open(filepath, 'w', encoding='utf-8') as f:
        for row in cur:
            f.write(row[0] + '\n')
    return cur.rowcount


def import_entries(conn, filepath):
    """Import entries from a file (one per line)."""
    n = 0
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                store(conn, line)
                n += 1
    return n


def sync(local_conn, remote_path):
    """
    Sync local database with remote database.
    - Push: local entries not in remote -> remote
    - Pull: remote entries not in local -> local
    Returns (pushed, pulled) counts.
    """
    remote_conn = init_db(remote_path)

    # Get all UUIDs from both databases
    local_cur = local_conn.execute("SELECT uuid, content, created_at FROM entries")
    local_entries = {row[0]: (row[1], row[2]) for row in local_cur.fetchall()}

    remote_cur = remote_conn.execute("SELECT uuid, content, created_at FROM entries")
    remote_entries = {row[0]: (row[1], row[2]) for row in remote_cur.fetchall()}

    local_uuids = set(local_entries.keys())
    remote_uuids = set(remote_entries.keys())

    # Push: entries in local but not remote
    to_push = local_uuids - remote_uuids
    for uuid in to_push:
        content, created_at = local_entries[uuid]
        remote_conn.execute(
            "INSERT INTO entries (content, uuid, created_at) VALUES (?, ?, ?)",
            (content, uuid, created_at)
        )
    remote_conn.commit()

    # Pull: entries in remote but not local
    to_pull = remote_uuids - local_uuids
    for uuid in to_pull:
        content, created_at = remote_entries[uuid]
        local_conn.execute(
            "INSERT INTO entries (content, uuid, created_at) VALUES (?, ?, ?)",
            (content, uuid, created_at)
        )
    local_conn.commit()

    remote_conn.close()
    return len(to_push), len(to_pull)


def run_repl():
    """Main REPL loop."""
    conn = init_db()

    print("vanavar - associative memory")
    print(f"db: {DB_PATH}")
    print(f"({count(conn)} entries)")
    print("Type 'help' for commands\n")

    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not text:
            continue

        lower = text.lower()

        # Commands
        if lower in ('quit', 'exit', 'bye', 'q'):
            print("Bye!")
            break

        elif lower in ('help', '?'):
            print("""
Store anything - just type it:
    VSNT reporter "Alex Sherman" alex@vsnt.com @sherman4949
    Project Alpha deadline 2024-03-15 contact: bob@acme.com

Find by any term (prefix match by default):
    find alex           - matches alex, alexander, alexis...
    find alex$          - exact match only (alex, not alexander)
    find alex VSNT      - multiple terms (AND)

Edit entries:
    edit alex           - find matches, pick one to edit

Commands:
    list                - show recent entries
    delete <term>       - delete entries matching term
    count               - show total entries
    import <file>       - import entries from file
    export <file>       - export entries to file
    sync <path>         - sync with shared database
    quit                - exit
""")

        elif lower == 'list':
            entries = list_all(conn)
            if entries:
                for rowid, content in entries:
                    print(f"  {content}")
            else:
                print("No entries yet.")

        elif lower == 'count':
            print(f"{count(conn)} entries")

        elif lower.startswith('find '):
            terms = text[5:].split()
            if len(terms) == 1:
                results = find(conn, terms[0])
            else:
                results = find_all(conn, terms)
            if results:
                for rowid, content in results:
                    print(f"  {content}")
            else:
                print("Nothing found.")

        elif lower.startswith('edit '):
            term = text[5:]
            results = find(conn, term)
            if not results:
                print("Nothing found.")
            elif len(results) == 1:
                rowid, content = results[0]
                try:
                    new_content = input_with_prefill("Edit: ", content).strip()
                    if new_content and new_content != content:
                        update_entry(conn, rowid, new_content)
                        print("Updated.")
                    else:
                        print("(no change)")
                except (EOFError, KeyboardInterrupt):
                    print("\n(cancelled)")
            else:
                print("Multiple matches - pick one:")
                for i, (rowid, content) in enumerate(results, 1):
                    print(f"  {i}. {content}")
                try:
                    choice = input("Number (or Enter to cancel): ").strip()
                    if choice.isdigit() and 1 <= int(choice) <= len(results):
                        rowid, content = results[int(choice) - 1]
                        new_content = input_with_prefill("Edit: ", content).strip()
                        if new_content and new_content != content:
                            update_entry(conn, rowid, new_content)
                            print("Updated.")
                        else:
                            print("(no change)")
                    else:
                        print("(cancelled)")
                except (EOFError, KeyboardInterrupt):
                    print("\n(cancelled)")

        elif lower.startswith('delete '):
            term = text[7:]
            results = find(conn, term)
            if not results:
                print("Nothing found.")
            elif len(results) == 1:
                rowid, content = results[0]
                print(f"Delete: {content}")
                try:
                    confirm = input("Confirm? (y/N): ").strip().lower()
                    if confirm == 'y':
                        delete_by_id(conn, rowid)
                        print("Deleted.")
                    else:
                        print("(cancelled)")
                except (EOFError, KeyboardInterrupt):
                    print("\n(cancelled)")
            else:
                print("Multiple matches:")
                for i, (rowid, content) in enumerate(results, 1):
                    print(f"  {i}. {content}")
                try:
                    choice = input("Number to delete (or 'all', or Enter to cancel): ").strip()
                    if choice.isdigit() and 1 <= int(choice) <= len(results):
                        rowid, content = results[int(choice) - 1]
                        delete_by_id(conn, rowid)
                        print("Deleted.")
                    elif choice.lower() == 'all':
                        for rowid, content in results:
                            delete_by_id(conn, rowid)
                        print(f"Deleted {len(results)} entries.")
                    else:
                        print("(cancelled)")
                except (EOFError, KeyboardInterrupt):
                    print("\n(cancelled)")

        elif lower.startswith('import '):
            filepath = text[7:].strip()
            try:
                n = import_entries(conn, filepath)
                print(f"Imported {n} entries.")
            except FileNotFoundError:
                print(f"File not found: {filepath}")
            except Exception as e:
                print(f"Error: {e}")

        elif lower.startswith('export '):
            filepath = text[7:].strip()
            try:
                cur = conn.execute("SELECT content FROM entries ORDER BY created_at")
                entries = cur.fetchall()
                with open(filepath, 'w', encoding='utf-8') as f:
                    for row in entries:
                        f.write(row[0] + '\n')
                print(f"Exported {len(entries)} entries to {filepath}")
            except Exception as e:
                print(f"Error: {e}")

        elif lower.startswith('sync '):
            remote_path = text[5:].strip()
            if not remote_path:
                print("Usage: sync <path-to-shared-db>")
            else:
                try:
                    pushed, pulled = sync(conn, remote_path)
                    print(f"Synced: pushed {pushed}, pulled {pulled}")
                except Exception as e:
                    print(f"Sync error: {e}")

        elif lower == 'sync':
            print("Usage: sync <path-to-shared-db>")

        else:
            # Store as a new entry
            store(conn, text)
            print("Stored.")

    conn.close()


if __name__ == "__main__":
    run_repl()
