"""
SQLite database for storing chat conversations and messages.
"""

import re
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


def list_conversations(query: str | None = None) -> list[dict]:
    """
    List conversations, most recently ACTIVE first.

    Ordering is by last message, not by created_at. Sorting by creation date
    buried any chat that was started a while ago and picked up again later -
    it stayed pinned to wherever it began, so carrying on an old thread made
    it no easier to find.

    `query` searches the title AND the text of every message, so a chat can be
    found by something said inside it rather than only by its first line. The
    titles are auto-generated from the opening message, which means half of
    them read "Create a social media post"; matching on content is the only
    way to tell those apart. Returns a `snippet` for content matches so the
    sidebar can show WHERE it hit.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.created_at,
                   COUNT(m.id) AS message_count,
                   COALESCE(MAX(m.created_at), c.created_at) AS last_at
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY last_at DESC
            """
        ).fetchall()
        convos = [dict(row) for row in rows]

        if not query or not query.strip():
            return convos

        # LIKE with an escape char - a literal % or _ in his search text must
        # not turn into a wildcard.
        needle = query.strip()
        like = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

        hits = conn.execute(
            """
            SELECT conversation_id, role, content
            FROM messages
            WHERE content LIKE ? ESCAPE '\\'
            ORDER BY created_at ASC, id ASC
            """,
            (like,),
        ).fetchall()

        first_hit: dict[str, str] = {}
        for row in hits:
            if row["conversation_id"] in first_hit:
                continue
            first_hit[row["conversation_id"]] = _snippet(row["content"], needle)

        low = needle.lower()
        results = []
        for c in convos:
            title_match = low in (c["title"] or "").lower()
            if c["id"] in first_hit:
                c["snippet"] = first_hit[c["id"]]
                results.append(c)
            elif title_match:
                results.append(c)
        return results
    finally:
        conn.close()


def _snippet(content: str, needle: str, width: int = 60) -> str:
    """A window of `content` centred on the match, for the sidebar preview.

    The stored replies are markdown, so a raw slice shows things like
    "87 Monte Dr** - **Signing". Strip the formatting characters - the sidebar
    renders plain text and the asterisks only read as noise.
    """
    idx = content.lower().find(needle.lower())
    if idx < 0:
        start, end = 0, min(len(content), width)
    else:
        start = max(0, idx - width // 3)
        end = min(len(content), idx + len(needle) + width)

    out = re.sub(r"[*_`#>]+", "", content[start:end])
    out = re.sub(r"\s+", " ", out).strip()
    return ("..." if start > 0 else "") + out + ("..." if end < len(content) else "")


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
