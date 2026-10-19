"""Encrypted API key storage manager.

Uses Fernet encryption (same approach as backup.py) to encrypt/decrypt
the AI API configuration file. Supports key rotation.
"""

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SECURITY_DIR = PROJECT / "security"
DATA_DIR = PROJECT / "data"

CONFIG_PATH = DATA_DIR / "ai_api_config.json"
ENCRYPTED_PATH = DATA_DIR / "ai_api_config.enc.json"

_API_KEY_ENV = "DUA_API_KEY"

REQUIRED_FIELDS = {"base_url", "api_keys", "models"}


def _get_encryption_key():
    """Get or derive a Fernet key for API config encryption."""

    raw = os.environ.get(_API_KEY_ENV)
    if raw:
        return raw.encode() if isinstance(raw, str) else raw

    salt_path = SECURITY_DIR / "salt.bin"
    seed = str(PROJECT).encode()
    if salt_path.exists():
        seed += salt_path.read_bytes()
    else:
        seed += b"dua-api-config-fallback"

    h = hashlib.sha256(seed).digest()
    return base64.urlsafe_b64encode(h)


def encrypt_config():
    """Encrypt the plaintext config file to an encrypted file."""
    from cryptography.fernet import Fernet

    if not CONFIG_PATH.exists():
        print(f"Error: {CONFIG_PATH} not found", file=sys.stderr)
        sys.exit(1)

    plaintext = CONFIG_PATH.read_text(encoding="utf-8")
    try:
        data = json.loads(plaintext)
    except json.JSONDecodeError as e:
        print(f"Error: {CONFIG_PATH} is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        print(f"Warning: Config missing fields: {missing}", file=sys.stderr)

    key = _get_encryption_key()
    cipher = Fernet(key)
    token = cipher.encrypt(plaintext.encode("utf-8"))

    encrypted_payload = {
        "encrypted": True,
        "data": token.decode("utf-8"),
    }
    ENCRYPTED_PATH.write_text(json.dumps(encrypted_payload, indent=2), encoding="utf-8")
    print(f"Encrypted config written to {ENCRYPTED_PATH}")


def decrypt_config():
    """Decrypt the encrypted config file back to plaintext."""
    from cryptography.fernet import Fernet

    if not ENCRYPTED_PATH.exists():
        print(f"Error: {ENCRYPTED_PATH} not found", file=sys.stderr)
        sys.exit(1)

    payload = json.loads(ENCRYPTED_PATH.read_text(encoding="utf-8"))
    if not payload.get("encrypted") or "data" not in payload:
        print("Error: Invalid encrypted file format", file=sys.stderr)
        sys.exit(1)

    key = _get_encryption_key()
    cipher = Fernet(key)
    try:
        plaintext = cipher.decrypt(payload["data"].encode("utf-8")).decode("utf-8")
    except Exception as e:
        print(f"Decryption failed: {e}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(plaintext)

    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        print(
            f"Error: Decrypted config missing required fields: {missing}",
            file=sys.stderr,
        )
        sys.exit(1)

    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Decrypted config written to {CONFIG_PATH}")


def rotate_key(new_api_key: str):
    """Add a new API key to the encrypted config."""
    from cryptography.fernet import Fernet

    if not ENCRYPTED_PATH.exists():
        print(f"Error: {ENCRYPTED_PATH} not found. Encrypt config first.", file=sys.stderr)
        sys.exit(1)

    payload = json.loads(ENCRYPTED_PATH.read_text(encoding="utf-8"))
    if not payload.get("encrypted") or "data" not in payload:
        print("Error: Invalid encrypted file format", file=sys.stderr)
        sys.exit(1)

    key = _get_encryption_key()
    cipher = Fernet(key)
    try:
        plaintext = cipher.decrypt(payload["data"].encode("utf-8")).decode("utf-8")
    except Exception as e:
        print(f"Decryption failed: {e}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(plaintext)

    if new_api_key in data.get("api_keys", []):
        print("Key already exists in config.")
        return

    data.setdefault("api_keys", []).append(new_api_key)

    new_plaintext = json.dumps(data, indent=2).encode("utf-8")
    new_token = cipher.encrypt(new_plaintext)
    ENCRYPTED_PATH.write_text(
        json.dumps({"encrypted": True, "data": new_token.decode("utf-8")}, indent=2),
        encoding="utf-8",
    )
    print(f"Added new API key. Total keys: {len(data['api_keys'])}")


def main():
    if len(sys.argv) < 2:
        print("Usage: api_key_manager.py <encrypt|decrypt|rotate-key> [new_api_key]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "encrypt":
        encrypt_config()
    elif command == "decrypt":
        decrypt_config()
    elif command == "rotate-key":
        if len(sys.argv) < 3:
            print("Usage: api_key_manager.py rotate-key <new_api_key>", file=sys.stderr)
            sys.exit(1)
        rotate_key(sys.argv[2])
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Commands: encrypt, decrypt, rotate-key")
        sys.exit(1)


if __name__ == "__main__":
    main()
