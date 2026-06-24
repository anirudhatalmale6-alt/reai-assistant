"""
SQLite database for storing chat conversations and messages.
"""

import sqlite3
import uuid
from datetime import datetime, timezone

from app.config import settings

DB_PATH = settings.BASE_DIR / "data" / "reai.db"


def _get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create database tables if they don't exist."""
    conn = _get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
                ON messages(conversation_id);
        """)
        conn.commit()
    finally:
        conn.close()


def create_conversation(conversation_id: str | None = None) -> str:
    """
    Create a new conversation. Returns the conversation ID.
    If no ID is provided, generates a UUID.
    """
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at) VALUES (?, ?, ?)",
            (conversation_id, "New Conversation", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    return conversation_id


def save_message(conversation_id: str, role: str, content: str) -> int:
    """
    Save a message to a conversation. Creates the conversation if it
    doesn't exist. Returns the message ID.
    """
    conn = _get_connection()
    try:
        # Ensure conversation exists
        row = conn.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at) VALUES (?, ?, ?)",
                (conversation_id, "New Conversation", datetime.now(timezone.utc).isoformat()),
            )

        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_messages(conversation_id: str) -> list[dict]:
    """
    Retrieve all messages for a conversation, ordered chronologically.
    Returns a list of dicts with keys: id, conversation_id, role, content, created_at.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT id, conversation_id, role, content, created_at "
            "FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, id ASC",
            (conversation_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_conversations() -> list[dict]:
    """
    List all conversations ordered by most recent first.
    Returns a list of dicts with keys: id, title, created_at, message_count.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.created_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_conversation(conversation_id: str) -> bool:
    """
    Delete a conversation and all its messages.
    Returns True if the conversation existed and was deleted.
    """
    conn = _get_connection()
    try:
        # Messages are cascade-deleted via FK
        cursor = conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_conversation_title(conversation_id: str, title: str) -> bool:
    """
    Update the title of a conversation.
    Returns True if the conversation existed and was updated.
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title, conversation_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# Initialize the database on module import
init_db()
