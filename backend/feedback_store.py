from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = Path(__file__).resolve().parent / "data" / "feedback.sqlite3"


def save_feedback(
    payload: dict[str, Any], database: Path = DEFAULT_DATABASE
) -> int:
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                classification_correct INTEGER NOT NULL,
                recommendation_useful INTEGER NOT NULL,
                overall_rating INTEGER NOT NULL CHECK (overall_rating BETWEEN 1 AND 5),
                component TEXT,
                comments TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        cursor = connection.execute(
            """
            INSERT INTO feedback (
                classification_correct, recommendation_useful, overall_rating,
                component, comments, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(payload["classification_correct"]),
                int(payload["recommendation_useful"]),
                payload["overall_rating"],
                payload.get("component"),
                payload.get("comments", ""),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return int(cursor.lastrowid)
