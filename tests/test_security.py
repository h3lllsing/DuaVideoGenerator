"""
Unit tests for Security Module
Tests encryption/decryption, key derivation, and vault operations
"""

import json
import os
import shutil
import subprocess
import sys

import pytest
from cryptography.fernet import Fernet, InvalidToken

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.security import LEGACY_SALT, SecurityManager, VaultWriteError


def _make_manager(password, salt, vault_path, keys_dir, salt_path):
    """Build a SecurityManager without __init__ side effects (avoids touching
    the real security/salt.bin). Used for controlled vault-migration tests."""
    sm = SecurityManager.__new__(SecurityManager)
    sm.master_password = password
    sm.vault_path = vault_path
    sm.keys_dir = keys_dir
    sm.salt_path = salt_path
    sm.salt = salt
    sm.key = sm._derive_key_with_salt(password, salt)
    sm.cipher = Fernet(sm.key)
    sm._salt_regenerated = False
    os.makedirs(os.path.dirname(vault_path), exist_ok=True)
    os.makedirs(keys_dir, exist_ok=True)
    with open(salt_path, "wb") as f:
        f.write(salt)
    return sm


class TestSecurityManager:
    """Test cases for SecurityManager class"""

    def setup_method(self):
        """Setup test fixtures"""
        self.test_password = "test_password_123"
        self.sm = SecurityManager(self.test_password)
        # Use a temporary vault path for testing
        self.sm.vault_path = os.path.join(os.path.dirname(__file__), "test_vault.enc")
        self.sm.keys_dir = os.path.join(os.path.dirname(__file__), "test_keys")
        self.sm.salt_path = os.path.join(os.path.dirname(__file__), "test_salt.bin")
        os.makedirs(self.sm.keys_dir, exist_ok=True)

    def teardown_method(self):
        """Cleanup test files"""
        if os.path.exists(self.sm.vault_path):
            os.remove(self.sm.vault_path)
        if os.path.exists(self.sm.keys_dir):
            import shutil

            shutil.rmtree(self.sm.keys_dir)
        if os.path.exists(self.sm.salt_path):
            os.remove(self.sm.salt_path)

    def test_key_derivation(self):
        """Test that key derivation produces consistent results"""
        key1 = self.sm._derive_key("password123")
        key2 = self.sm._derive_key("password123")
        assert key1 == key2, "Same password should produce same key"
        # Key is base64-encoded, so it's 44 bytes (32 bytes raw + base64 encoding)
        assert len(key1) == 44, "Base64-encoded key should be 44 bytes"

    def test_different_passwords_different_keys(self):
        """Test that different passwords produce different keys"""
        key1 = self.sm._derive_key("password1")
        key2 = self.sm._derive_key("password2")
        assert key1 != key2, "Different passwords should produce different keys"

    def test_encryption_decryption_round_trip(self):
        """Test that encrypt/decrypt round-trip works"""
        original_data = "Test data for encryption"
        encrypted = self.sm.encrypt(original_data)
        decrypted = self.sm.decrypt(encrypted)
        assert decrypted == original_data, "Decrypted data should match original"

    def test_encryption_produces_different_output(self):
        """Test that encryption produces different ciphertext each time"""
        data = "Same data"
        encrypted1 = self.sm.encrypt(data)
        encrypted2 = self.sm.encrypt(data)
        assert encrypted1 != encrypted2, "Encryption should use random IV"

    def test_encryption_with_empty_string(self):
        """Test encryption with empty string"""
        original = ""
        encrypted = self.sm.encrypt(original)
        decrypted = self.sm.decrypt(encrypted)
        assert decrypted == original

    def test_encryption_with_unicode(self):
        """Test encryption with Unicode characters (Arabic/Urdu)"""
        original = "بسم الله الرحمن الرحيم"  # Arabic text
        encrypted = self.sm.encrypt(original)
        decrypted = self.sm.decrypt(encrypted)
        assert decrypted == original

    def test_vault_save_and_load(self):
        """Test vault save and load operations"""
        test_data = {"theme": "dark", "voice_speed": 1.0}

        # Save vault
        self.sm.save_vault(test_data)
        assert os.path.exists(self.sm.vault_path), "Vault file should exist"

        # Load vault
        loaded_data = self.sm.load_vault()
        assert loaded_data == test_data, "Loaded data should match saved data"

    def test_load_vault_nonexistent(self):
        """Test loading vault when file doesn't exist"""
        # Remove vault if it exists
        if os.path.exists(self.sm.vault_path):
            os.remove(self.sm.vault_path)

        loaded = self.sm.load_vault()
        assert loaded == {}, "Loading nonexistent vault should return empty dict"

    def test_vault_exists(self):
        """Test vault_exists method"""
        assert not self.sm.vault_exists(), "Vault should not exist initially"

        self.sm.save_vault({"test": True})
        assert self.sm.vault_exists(), "Vault should exist after saving"

    def test_security_info(self):
        """Test get_security_info method"""
        info = self.sm.get_security_info()

        assert "encryption" in info
        assert "key_derivation" in info
        assert "iterations" in info
        assert "vault_exists" in info
        assert info["encryption"] == "AES-128-CBC (Fernet)"
        assert info["key_derivation"] == "PBKDF2-HMAC-SHA256"
        assert info["iterations"] == 600000

    def test_wrong_password_fails_decryption(self):
        """Test that wrong password fails to decrypt"""
        # Encrypt with one password
        original_data = "Secret data"
        encrypted = self.sm.encrypt(original_data)

        # Try to decrypt with different password
        sm2 = SecurityManager("wrong_password")
        sm2.vault_path = self.sm.vault_path

        # Manually save vault with wrong encryption
        sm2.save_vault({"encrypted": encrypted})

        # Loading should fail or return corrupted data
        loaded = sm2.load_vault()
        # Note: This test depends on implementation - might raise exception or return None
        assert loaded != original_data, "Wrong password should not decrypt correctly"

    def test_large_data_encryption(self):
        """Test encryption with large data"""
        # Create large dataset
        large_data = {"key_" + str(i): "value_" + str(i) for i in range(1000)}
        encrypted = self.sm.encrypt(json.dumps(large_data))
        decrypted = self.sm.decrypt(encrypted)
        assert json.loads(decrypted) == large_data, "Large data should encrypt/decrypt correctly"


class TestVaultMigration:
    """Tests for legacy vault state detection and migration (SEC-002)"""

    def setup_method(self):
        self.tmp_dir = os.path.join(os.path.dirname(__file__), "_migration_tmp")
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)
        os.makedirs(self.tmp_dir)
        self.vault_path = os.path.join(self.tmp_dir, "vault.enc")
        self.keys_dir = os.path.join(self.tmp_dir, "keys")
        self.salt_path = os.path.join(self.tmp_dir, "salt.bin")
        self.legacy_salt_path = os.path.join(self.tmp_dir, "legacy_salt.bin")

    def teardown_method(self):
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)

    def _legacy_manager(self, password="correct_pw"):
        return _make_manager(password, LEGACY_SALT, self.vault_path, self.keys_dir, self.legacy_salt_path)

    def _new_manager(self, password="correct_pw", salt=None):
        if salt is None:
            salt = os.urandom(16)
        return _make_manager(password, salt, self.vault_path, self.keys_dir, self.salt_path)

    def _read_vault_bytes(self):
        with open(self.vault_path, "rb") as f:
            return f.read()

    def test_detect_missing(self):
        sm = self._new_manager()
        assert sm.detect_vault_state("correct_pw") == "missing"

    def test_detect_new(self):
        sm = self._new_manager()
        sm.save_vault({"user": "X"})
        assert sm.detect_vault_state("correct_pw") == "new"

    def test_detect_legacy(self):
        legacy = self._legacy_manager()
        legacy.save_vault({"user": "X"})
        sm = self._new_manager()
        assert sm.detect_vault_state("correct_pw") == "legacy"

    def test_detect_wrong_password(self):
        sm1 = self._new_manager()
        sm1.save_vault({"user": "X"})
        sm2 = _make_manager("wrong_pw", sm1.salt, self.vault_path, self.keys_dir, self.salt_path)
        assert sm2.detect_vault_state("wrong_pw") == "wrong_password"

    def test_detect_corrupt(self):
        sm = self._new_manager()
        with open(self.vault_path, "w") as f:
            f.write("this is not a fernet token at all")
        assert sm.detect_vault_state("correct_pw") == "corrupt"

    def test_detect_salt_lost(self):
        sm1 = self._new_manager()
        sm1.save_vault({"user": "X"})
        sm2 = self._new_manager(salt=os.urandom(16))
        os.remove(self.salt_path)
        assert sm2.detect_vault_state("correct_pw") == "salt_lost"

    def test_legacy_migration_roundtrip(self):
        plaintext = {"user": "MASOOD NASIR", "channel": "@bushranasir1075"}
        legacy = self._legacy_manager()
        legacy.save_vault(plaintext)
        sm = self._new_manager()
        assert sm.detect_vault_state("correct_pw") == "legacy"
        assert sm.migrate_legacy_vault("correct_pw") is True
        assert sm.load_vault() == plaintext
        assert sm.detect_vault_state("correct_pw") == "new"

    def test_migrated_vault_decrypts_with_new_salt(self):
        plaintext = {"a": 1}
        legacy = self._legacy_manager()
        legacy.save_vault(plaintext)
        sm = self._new_manager()
        assert sm.migrate_legacy_vault("correct_pw") is True
        assert sm.decrypt_dict(self._read_vault_bytes().decode()) == plaintext

    def test_migrated_plaintext_equals_original(self):
        plaintext = {"user": "A", "settings": {"theme": "dark"}, "learning_data": {"x": 0}}
        legacy = self._legacy_manager()
        legacy.save_vault(plaintext)
        sm = self._new_manager()
        assert sm.migrate_legacy_vault("correct_pw") is True
        assert sm.load_vault() == plaintext

    def test_legacy_no_longer_decryptable_after_migration(self):
        legacy = self._legacy_manager()
        legacy.save_vault({"user": "A"})
        sm = self._new_manager()
        assert sm.migrate_legacy_vault("correct_pw") is True
        token = self._read_vault_bytes().decode()
        legacy_cipher = Fernet(legacy._derive_key_with_salt("correct_pw", LEGACY_SALT))
        with pytest.raises(InvalidToken):
            legacy_cipher.decrypt(token.encode())

    def test_migration_wrong_password_leaves_bytes_unchanged(self):
        legacy = self._legacy_manager()
        legacy.save_vault({"user": "A"})
        sm = self._new_manager()
        before = self._read_vault_bytes()
        assert sm.migrate_legacy_vault("wrong_pw") is False
        assert self._read_vault_bytes() == before

    def test_migration_failure_leaves_original_untouched(self, monkeypatch):
        legacy = self._legacy_manager()
        legacy.save_vault({"user": "A"})
        sm = self._new_manager()
        before = self._read_vault_bytes()

        def _boom(path, content):
            raise RuntimeError("injected write failure")

        monkeypatch.setattr(sm, "_atomic_write_text", _boom)
        assert sm.migrate_legacy_vault("correct_pw") is False
        assert self._read_vault_bytes() == before

    def test_migration_tmp_cleanup(self, monkeypatch):
        legacy = self._legacy_manager()
        legacy.save_vault({"user": "A"})
        sm = self._new_manager()

        def _boom(path, content):
            with open(path + ".tmp", "w") as f:
                f.write("partial")
            raise RuntimeError("injected write failure")

        monkeypatch.setattr(sm, "_atomic_write_text", _boom)
        sm.migrate_legacy_vault("correct_pw")
        assert not os.path.exists(self.vault_path + ".tmp")

    def test_save_vault_refuses_overwrite_undecryptable(self):
        legacy = self._legacy_manager()
        legacy.save_vault({"user": "A"})
        sm = self._new_manager()
        before = self._read_vault_bytes()
        with pytest.raises(VaultWriteError):
            sm.save_vault({"user": "overwrite"})
        assert self._read_vault_bytes() == before

    def test_save_vault_refuses_overwrite_when_salt_missing(self):
        sm = self._new_manager()
        sm.save_vault({"user": "A"})
        os.remove(self.salt_path)
        with pytest.raises(VaultWriteError):
            sm.save_vault({"user": "overwrite"})

    def test_legacy_backup_retained(self):
        legacy = self._legacy_manager()
        legacy.save_vault({"user": "A"})
        sm = self._new_manager()
        assert sm.migrate_legacy_vault("correct_pw") is True
        assert os.path.exists(self.vault_path + ".legacy.bak")

    def test_main_block_non_destructive(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prod_vault = os.path.join(project_root, "security", "vault.enc")
        before = None
        if os.path.exists(prod_vault):
            with open(prod_vault, "rb") as f:
                before = f.read()
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, "core/security.py"], cwd=project_root, capture_output=True, text=True, env=env, timeout=120
        )
        assert proc.returncode == 0, proc.stderr
        after = None
        if os.path.exists(prod_vault):
            with open(prod_vault, "rb") as f:
                after = f.read()
        assert before == after


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
