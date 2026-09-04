"""
Database layer for the bot's conversation memory.

WHY THIS FILE EXISTS: previously conversation history lived only in a
Python dict in RAM (conversation_history = {}), which is wiped every
time the bot process restarts. This file replaces that with SQLite --
a serverless, file-based database built into Python's standard library
(the `sqlite3` module -- no `pip install` needed, no separate database
server to run). All data lives in one file, `bot_database.db`, that
persists on disk between restarts.

We keep all the database logic in ONE place (this file) so bot.py
doesn't need to know any SQL -- it just calls plain Python functions
like save_message() and load_history().
"""

import sqlite3

DB_FILE = "bot_database.db"


def init_db() -> None:
    """Create the messages table if it doesn't already exist.
    Call this once when the bot starts up.

    A table is like a spreadsheet: each row is one stored chat message.
    Columns:
      id         -- auto-incrementing unique number for each row
                    (SQLite creates this automatically for us)
      chat_id    -- which Telegram chat this message belongs to
      role       -- "user" or "assistant" (who sent it)
      content    -- the actual message text
      created_at -- timestamp, filled in automatically by SQLite
    """
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()
    connection.close()


def save_message(chat_id: int, role: str, content: str) -> None:
    """Insert one message row into the database."""
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
        (chat_id, role, content),
    )
    connection.commit()
    connection.close()


def load_history(chat_id: int, limit: int = 20) -> list[dict]:
    """Return this chat's most recent messages as a list of
    {"role": ..., "content": ...} dicts, oldest first -- ready to drop
    straight into the `messages` list the DeepSeek API expects.
    """
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT role, content FROM messages
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (chat_id, limit),
    )
    rows = cursor.fetchall()
    connection.close()

    # We queried newest-first (so LIMIT keeps the most RECENT messages),
    # but the conversation needs to read oldest-first -- so reverse it.
    rows.reverse()
    return [{"role": role, "content": content} for role, content in rows]


def clear_history(chat_id: int) -> None:
    """Delete all stored messages for one chat (used by /reset)."""
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
    connection.commit()
    connection.close()
