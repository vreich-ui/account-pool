"""Vault: envelope encryption, secret-by-reference, and key isolation."""

from __future__ import annotations

import pytest
from cryptography.fernet import InvalidToken

from account_pool.domain.enums import AuthType, Platform
from account_pool.vault.keyref import generate_key
from account_pool.vault.provider import BuiltinConnectionProvider
from account_pool.vault.vault import EncryptedVault, SecretNotFound


def test_round_trip_and_envelope():
    v = EncryptedVault(generate_key().encode(), ":memory:")
    ref = v.store({"access_token": "abc", "refresh_token": "def"})
    assert v.retrieve(ref) == {"access_token": "abc", "refresh_token": "def"}
    assert v.exists(ref)


def test_secret_value_never_on_connection_metadata():
    v = EncryptedVault(generate_key().encode(), ":memory:")
    provider = BuiltinConnectionProvider(v)
    conn = provider.store_credentials(
        "acct1", Platform.REDDIT, AuthType.OAUTH2, {"access_token": "TOPSECRET"}, ["identity"]
    )
    dumped = conn.model_dump_json()
    assert "TOPSECRET" not in dumped  # only a secret_ref pointer travels with metadata
    assert conn.secret_ref
    assert provider.load_credentials(conn)["access_token"] == "TOPSECRET"


def test_wrong_master_key_cannot_decrypt(tmp_path):
    store = str(tmp_path / "vault.db")
    good = EncryptedVault(generate_key().encode(), store)
    ref = good.store({"k": "v"})
    good.close()

    attacker = EncryptedVault(generate_key().encode(), store)
    with pytest.raises(InvalidToken):
        attacker.retrieve(ref)


def test_missing_ref_raises():
    v = EncryptedVault(generate_key().encode(), ":memory:")
    with pytest.raises(SecretNotFound):
        v.retrieve("vault_does_not_exist")


def test_delete():
    v = EncryptedVault(generate_key().encode(), ":memory:")
    ref = v.store({"k": "v"})
    v.delete(ref)
    assert not v.exists(ref)
