"""
Security Module - AES-128-CBC Encryption (Fernet)
All data encrypted at rest
"""

import base64
import hmac
import json
import logging
import os
from typing import Any, cast

logger = logging.getLogger(__name__)
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

__all__ = ["VaultWriteError", "SecurityManager"]

# Migration-only legacy salt used by vaults created before random-per-installation
# salts were introduced. Kept permanently so existing legacy vaults stay recoverable.
LEGACY_SALT = b"dua_video_generator_2026_salt"
PBKDF2_ITERATIONS = 600000


class VaultWriteError(Exception):
    """Raised when save_vault() is asked to overwrite an existing vault that
    cannot be authenticated/decrypted, or when the salt is missing."""


class SecurityManager:
    """
    Manages encryption and security for the Dua Video Generator.
    Uses AES-128-CBC encryption (Fernet) with PBKDF2 key derivation.
    """

    def __init__(self, master_password: str):
        """
        Initialize security manager with master password.

        Args:
            master_password: User's master password for encryption
        """
        self.master_password = master_password
        self._salt_regenerated = False
        self.vault_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "security", "vault.enc"
        )
        self.keys_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "security", "keys")
        self.salt_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "security", "salt.bin"
        )
        # Create directories if they don't exist
        os.makedirs(os.path.dirname(self.vault_path), exist_ok=True)
        os.makedirs(self.keys_dir, exist_ok=True)

        # Load or generate salt
        self.salt = self._load_or_generate_salt()
        self.key = self._derive_key(master_password)
        self.cipher = Fernet(self.key)

    def _load_or_generate_salt(self) -> bytes:
        """
        Load existing salt or generate a new one.

        Returns:
            16-byte salt for PBKDF2
        """
        if os.path.exists(self.salt_path):
            with open(self.salt_path, "rb") as f:
                return f.read()

        # Generate new random salt
        salt = os.urandom(16)
        with open(self.salt_path, "wb") as f:
            f.write(salt)
        self._salt_regenerated = True

        return salt

    def _derive_key(self, password: str) -> bytes:
        """
        Derive key from password using PBKDF2-HMAC-SHA256.
        Fernet uses the first 128 bits (16 bytes) of the derived key for AES-128-CBC.

        Args:
            password: Master password

        Returns:
            32-byte key for Fernet (uses 128 bits for AES-128-CBC)
        """
        return self._derive_key_with_salt(password, self.salt)

    def _derive_key_with_salt(self, password: str, salt: bytes) -> bytes:
        """
        Derive key from password and an explicit salt using PBKDF2-HMAC-SHA256.
        Used by the current-key path and by legacy-vault migration.

        Args:
            password: Master password
            salt: Salt bytes for PBKDF2

        Returns:
            32-byte key for Fernet (uses 128 bits for AES-128-CBC)
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )

        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key

    @staticmethod
    def _is_valid_fernet_token(token: str) -> bool:
        """
        Structurally validate a Fernet token without decrypting.
        Fernet tokens start with a version byte 0x80; malformed tokens and wrong
        keys both raise InvalidToken on decrypt, so structure must be checked
        manually to distinguish 'corrupt' from 'wrong password'.

        Args:
            token: Token string

        Returns:
            True if the token has valid Fernet structure
        """
        if not token or not isinstance(token, str):
            return False
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        except Exception:
            return False
        if len(raw) < 58:  # 1 version + 8 timestamp + 16 IV + 32 HMAC + 1 ciphertext
            return False
        if raw[0] != 0x80:
            return False
        return True

    def encrypt(self, data: str) -> str:
        """
        Encrypt string data.

        Args:
            data: Plain text string

        Returns:
            Encrypted string
        """
        return self.cipher.encrypt(data.encode()).decode()

    def decrypt(self, encrypted: str) -> str:
        """
        Decrypt encrypted data.

        Args:
            encrypted: Encrypted string

        Returns:
            Decrypted plain text
        """
        return self.cipher.decrypt(encrypted.encode()).decode()

    def encrypt_dict(self, data: dict) -> str:
        """
        Encrypt dictionary data.

        Args:
            data: Dictionary to encrypt

        Returns:
            Encrypted JSON string
        """
        json_str = json.dumps(data)
        return self.encrypt(json_str)

    def decrypt_dict(self, encrypted: str) -> dict:
        """
        Decrypt to dictionary.

        Args:
            encrypted: Encrypted JSON string

        Returns:
            Decrypted dictionary
        """
        json_str = self.decrypt(encrypted)
        return cast(dict[str, Any], json.loads(json_str))

    def save_vault(self, data: dict):
        """
        Save encrypted vault data.
        Refuses to overwrite an existing vault that cannot be authenticated
        with the current key, and refuses to re-encrypt an existing vault when
        salt.bin is missing (the vault may be unrecoverable).

        Args:
            data: Dictionary to save

        Raises:
            VaultWriteError: If the existing vault cannot be safely overwritten
        """
        if os.path.exists(self.vault_path):
            # Salt safety: never re-encrypt an existing vault when salt.bin is missing
            if not os.path.exists(self.salt_path):
                raise VaultWriteError(
                    "Refusing to overwrite existing vault: salt.bin is missing. The vault may be unrecoverable."
                )
            # Do not overwrite an existing vault we cannot authenticate/decrypt
            try:
                with open(self.vault_path) as f:
                    existing = f.read()
                self.cipher.decrypt(existing.encode())
            except Exception:
                raise VaultWriteError("Refusing to overwrite existing vault: could not authenticate/decrypt it.")
        encrypted = self.encrypt_dict(data)
        self._atomic_write_text(self.vault_path, encrypted)

    @staticmethod
    def _atomic_write_text(path: str, content: str):
        """
        Write text content to a file atomically: write to a sibling temp file,
        flush/fsync, then os.replace() over the destination.

        Args:
            path: Destination file path
            content: Text to write
        """
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

    def load_vault(self) -> dict:
        """
        Load encrypted vault data.

        Returns:
            Decrypted dictionary, empty dict if no vault exists
        """
        if not os.path.exists(self.vault_path):
            return {}

        try:
            with open(self.vault_path) as f:
                encrypted = f.read()
            return self.decrypt_dict(encrypted)
        except Exception:
            return {}

    def vault_exists(self) -> bool:
        """
        Check if vault file exists.

        Returns:
            True if vault exists
        """
        return os.path.exists(self.vault_path)

    def detect_vault_state(self, password: str) -> str:
        """
        Classify the vault's state to drive startup/launcher flow.

        Returns:
            'missing'      - no vault file (first run)
            'new'          - vault decrypts with the current salt
            'legacy'       - vault decrypts only with the legacy salt
            'wrong_password' - vault exists, current and legacy keys both fail,
                               salt.bin is present
            'corrupt'      - vault file missing/invalid Fernet structure
            'salt_lost'    - vault exists but cannot be decrypted and salt.bin
                             is missing or was just regenerated
        """
        if not os.path.exists(self.vault_path):
            return "missing"
        try:
            with open(self.vault_path) as f:
                token = f.read()
        except Exception:
            return "corrupt"
        if not self._is_valid_fernet_token(token):
            return "corrupt"
        # Try current salt
        try:
            self.cipher.decrypt(token.encode())
            return "new"
        except Exception:
            logger.debug("Current salt decrypt failed, trying legacy")
            pass
        # Try legacy salt
        try:
            legacy_cipher = Fernet(self._derive_key_with_salt(password, LEGACY_SALT))
            legacy_cipher.decrypt(token.encode())
            return "legacy"
        except Exception:
            logger.warning("Legacy salt decrypt also failed")
            pass
        salt_missing_now = not os.path.exists(self.salt_path)
        salt_was_regenerated = getattr(self, "_salt_regenerated", False)
        if salt_missing_now or salt_was_regenerated:
            return "salt_lost"
        return "wrong_password"

    def migrate_legacy_vault(self, password: str) -> bool:
        """
        Migrate a legacy vault (encrypted under the old hardcoded salt) to the
        current random salt. Decrypts in memory, re-encrypts with the current
        key, verifies the new token decrypts and matches, preserves the original
        bytes as <vault>.legacy.bak, then atomically replaces the vault.

        Args:
            password: Master password used for the legacy vault

        Returns:
            True if migration succeeded and the migrated vault was verified
        """
        if not os.path.exists(self.vault_path):
            return False
        backup_path = self.vault_path + ".legacy.bak"
        try:
            with open(self.vault_path) as f:
                legacy_token = f.read()
            if not self._is_valid_fernet_token(legacy_token):
                logger.error("Migration failed: vault token has invalid structure.")
                return False
            legacy_cipher = Fernet(self._derive_key_with_salt(password, LEGACY_SALT))
            plaintext_json = legacy_cipher.decrypt(legacy_token.encode()).decode()
            plaintext = json.loads(plaintext_json)
            # Re-encrypt under the current salt and verify in memory
            new_token = self.encrypt_dict(plaintext)
            if self.decrypt_dict(new_token) != plaintext:
                logger.error("Migration failed: re-encryption verification failed.")
                return False
            # Preserve the original bytes before touching the vault
            with open(backup_path, "wb") as f:
                f.write(legacy_token.encode())
            # Atomic replace
            self._atomic_write_text(self.vault_path, new_token)
            # Post-write verification under the NEW salt
            loaded = self.load_vault()
            if loaded != plaintext:
                logger.error("Post-write verification failed; restoring backup.")
                if os.path.exists(backup_path):
                    os.replace(backup_path, self.vault_path)
                return False
            return True
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            try:
                if os.path.exists(self.vault_path + ".tmp"):
                    os.remove(self.vault_path + ".tmp")
            except Exception:
                logger.debug("Tmp file cleanup skipped")
                pass
            return False

    def save_key(self, key_name: str, key_data: str):
        """
        Save an encrypted key (atomic write).

        Args:
            key_name: Name of the key
            key_data: Key data to encrypt and save
        """
        encrypted = self.encrypt(key_data)
        key_path = os.path.join(self.keys_dir, f"{key_name}.enc")
        tmp_path = key_path + f".{os.getpid()}.tmp"
        with open(tmp_path, "w") as f:
            f.write(encrypted)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, key_path)

    def load_key(self, key_name: str) -> str:
        """
        Load an encrypted key.

        Args:
            key_name: Name of the key

        Returns:
            Decrypted key data
        """
        key_path = os.path.join(self.keys_dir, f"{key_name}.enc")

        if not os.path.exists(key_path):
            return ""

        try:
            with open(key_path) as f:
                encrypted = f.read()
            return self.decrypt(encrypted)
        except Exception:
            return ""

    def secure_delete(self, file_path: str):
        """
        Securely delete file by overwriting with random data.

        Args:
            file_path: Path to file to delete
        """
        if not os.path.exists(file_path):
            return

        # Get file size
        size = os.path.getsize(file_path)

        # Overwrite with random data
        with open(file_path, "wb") as f:
            f.write(os.urandom(size))

        # Delete the file
        os.remove(file_path)

    def verify_password(self, password: str) -> bool:
        """
        Verify if password matches the master password.
        Uses constant-time comparison to prevent timing attacks.

        Args:
            password: Password to verify

        Returns:
            True if password matches
        """
        # encode to bytes: compare_digest rejects non-ASCII str comparisons
        return hmac.compare_digest(password.encode("utf-8"), (self.master_password or "").encode("utf-8"))

    def get_security_info(self) -> dict:
        """
        Get security information.

        Returns:
            Dictionary with security details
        """
        return {
            "encryption": "AES-128-CBC (Fernet)",
            "key_derivation": "PBKDF2-HMAC-SHA256",
            "iterations": PBKDF2_ITERATIONS,
            "vault_exists": self.vault_exists(),
            "keys_dir": self.keys_dir,
            "vault_path": self.vault_path,
            "salt_exists": os.path.exists(self.salt_path),
        }


# Self-test (NON-DESTRUCTIVE: uses temporary paths only, never touches the
# production security/vault.enc, keys, or salt.bin).
if __name__ == "__main__":
    import shutil
    import tempfile

    print("Testing Security Module (non-destructive, temp paths)...")

    tmpdir = tempfile.mkdtemp(prefix="dv_security_selftest_")
    try:
        security = SecurityManager("test_password_123")
        security.vault_path = os.path.join(tmpdir, "vault.enc")
        security.keys_dir = os.path.join(tmpdir, "keys")
        security.salt_path = os.path.join(tmpdir, "salt.bin")
        os.makedirs(security.keys_dir, exist_ok=True)
        # Regenerate salt under the temporary salt path
        security.salt = security._load_or_generate_salt()
        security.key = security._derive_key_with_salt("test_password_123", security.salt)
        security.cipher = Fernet(security.key)

        # Test encryption/decryption
        test_data = "بسم الله الرحمن الرحيم"
        encrypted = security.encrypt(test_data)
        decrypted = security.decrypt(encrypted)

        print(f"Original: {test_data}")
        print(f"Encrypted: {encrypted[:50]}...")
        print(f"Decrypted: {decrypted}")
        print(f"Match: {test_data == decrypted}")

        # Test vault
        vault_data = {"user": "MASOOD NASIR", "channel": "@bushranasir1075", "settings": {"theme": "dark"}}

        security.save_vault(vault_data)
        loaded_vault = security.load_vault()

        print(f"\nVault saved: {vault_data}")
        print(f"Vault loaded: {loaded_vault}")
        print(f"Vault match: {vault_data == loaded_vault}")

        # Test key storage
        security.save_key("youtube_api_key", "sample_api_key_12345")
        loaded_key = security.load_key("youtube_api_key")

        print("\nKey saved: sample_api_key_12345")
        print(f"Key loaded: {loaded_key}")
        print(f"Key match: {loaded_key == 'sample_api_key_12345'}")

        # Get security info
        print(f"\nSecurity Info: {security.get_security_info()}")

        print("\nSecurity Module Self-Test Complete (no production files touched).")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
