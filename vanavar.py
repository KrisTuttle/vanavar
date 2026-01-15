#!/usr/bin/env python3
"""
vanavar - associative memory

Store any line, find it by any term (prefix match by default).
    > VSNT reporter "Alex Sherman" alex.sherman@versantmedia.com @sherman4949
    > find alex
    > find VSNT
"""

import sqlite3
from pathlib import Path
from datetime import datetime

try:
    import readline
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False

DB_PATH = Path(__file__).parent / "vanavar.db"


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


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS entries USING fts5(
            content,
            created_at UNINDEXED
        )
    """)
    conn.commit()
    return conn


def store(conn, text):
    """Store a line."""
    conn.execute(
        "INSERT INTO entries (content, created_at) VALUES (?, ?)",
        (text, datetime.now().isoformat())
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
    count = 0
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                store(conn, line)
                count += 1
    return count


def run_repl():
    """Main REPL loop."""
    conn = init_db()

    print("vanavar - associative memory")
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

        else:
            # Store as a new entry
            store(conn, text)
            print("Stored.")

    conn.close()


if __name__ == "__main__":
    run_repl()
