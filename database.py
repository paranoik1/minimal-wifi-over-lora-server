from contextlib import contextmanager
from sqlite3 import Connection
import sqlite3

from core.packet import Packet
from config import DB_PATH


@contextmanager
def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with get_db() as db:
        UserRepository(db).init_table()


class UserRepository:
    def __init__(self, conn: Connection):
        self._conn = conn

    def init_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
                    CHECK(user_id BETWEEN 1 AND 15),

                name TEXT NOT NULL,
                secret_key TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def _generate_id(self) -> int:
        """
        Возвращает первый свободный UserId от 1 до Packet.max_user_id.
        """

        rows = self._conn.execute(
            "SELECT user_id FROM users"
        ).fetchall()

        used_ids = {
            row["user_id"]
            for row in rows
        }

        for user_id in range(1, Packet.max_user_id):
            if user_id not in used_ids:
                return user_id

        raise ValueError(f"Достигнут лимит пользователей ({Packet.max_user_id})")
    
    def get_users(self) -> list:
        return self._conn.execute("""
            SELECT user_id, name, created_at
            FROM users
            ORDER BY user_id
        """).fetchall()
    
    def get_secret_key(self, user_id: int) -> str:
        secret_key = self._conn.execute("""
            SELECT secret_key
            FROM users
            WHERE user_id = ?
        """, (user_id,)).fetchone()

        return secret_key

    def create_user(self, name: str, secret_key: str) -> int:
        """
        Insert user in db
        Return UserId
        """
        user_id = self._generate_id()

        self._conn.execute("""
            INSERT INTO users (
                user_id,
                name,
                secret_key
            )
            VALUES (?, ?, ?)
        """, (
            user_id, name, secret_key
        ))

        return user_id
    
    def delete_user(self, user_id: int) -> bool:
        cursor = self._conn.execute("""
            DELETE FROM users
            WHERE user_id = ?
        """, (user_id,))

        return cursor.rowcount != 0

    def set_secret_key(self, user_id: int, secret_key: str) -> bool:
        cursor = self._conn.execute("""
            UPDATE users
            SET secret_key = ?
            WHERE user_id = ?
        """, (
            secret_key, user_id
        ))

        return cursor.rowcount != 0
            
