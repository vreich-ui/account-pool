"""Encrypted, at-rest credential vault with envelope encryption.

Design points:

* The vault is a **separate store** from the metadata DB, so ciphertext never mingles with
  queryable records. Records elsewhere hold only an opaque ``secret_ref``.
* **Envelope encryption**: each secret gets its own random data key; the payload is encrypted with
  the data key, and the data key is wrapped with the master key. Rotating the master key only
  requires re-wrapping data keys, not re-encrypting payloads.
* Plaintext is never logged.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from cryptography.fernet import Fernet

from .. import clock
from ..domain.ids import secret_ref as new_secret_ref

_SCHEMA = """
CREATE TABLE IF NOT EXISTS secret_material (
    secret_ref  TEXT PRIMARY KEY,
    wrapped_key BLOB NOT NULL,
    ciphertext  BLOB NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


class SecretNotFound(KeyError):
    """Raised when a secret_ref is not present in the vault."""


class EncryptedVault:
    def __init__(self, master_key: bytes, store_path: str = ":memory:") -> None:
        self._master = Fernet(master_key)
        self._lock = threading.Lock()
        # check_same_thread=False so anyio worker threads can share the connection under our lock.
        self._conn = sqlite3.connect(store_path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def store(self, payload: dict[str, Any], secret_ref: str | None = None) -> str:
        """Encrypt and persist ``payload``; return its ``secret_ref`` (minted if not given)."""
        ref = secret_ref or new_secret_ref()
        data_key = Fernet.generate_key()
        ciphertext = Fernet(data_key).encrypt(json.dumps(payload).encode("utf-8"))
        wrapped_key = self._master.encrypt(data_key)
        ts = clock.now().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO secret_material (secret_ref, wrapped_key, ciphertext, created_at,
                                             updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(secret_ref) DO UPDATE SET
                    wrapped_key=excluded.wrapped_key,
                    ciphertext=excluded.ciphertext,
                    updated_at=excluded.updated_at
                """,
                (ref, wrapped_key, ciphertext, ts, ts),
            )
            self._conn.commit()
        return ref

    def retrieve(self, secret_ref: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT wrapped_key, ciphertext FROM secret_material WHERE secret_ref = ?",
                (secret_ref,),
            ).fetchone()
        if row is None:
            raise SecretNotFound(secret_ref)
        wrapped_key, ciphertext = row
        data_key = self._master.decrypt(wrapped_key)
        plaintext = Fernet(data_key).decrypt(ciphertext)
        return json.loads(plaintext.decode("utf-8"))

    def exists(self, secret_ref: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM secret_material WHERE secret_ref = ?", (secret_ref,)
            ).fetchone()
        return row is not None

    def delete(self, secret_ref: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM secret_material WHERE secret_ref = ?", (secret_ref,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
