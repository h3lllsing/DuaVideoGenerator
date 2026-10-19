"""
Backup Script for Dua Video Generator
Backs up vault, salt, tokens, and critical config files.
Sensitive files (auth.json, tokens) are encrypted with Fernet.
"""

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
BACKUP_DIR = PROJECT / "backups"
DATA_DIR = PROJECT / "data"
SECURITY_DIR = PROJECT / "security"
REMOTION_DIR = PROJECT / "remotion"

# Files to backup — (rel_path, description, encrypt?)
BACKUP_FILES = [
    # Security
    ("security/salt.bin", "Security salt", False),
    ("remotion/dashboard/auth.json", "Dashboard auth token", True),
    ("remotion/dashboard/config.json", "Dashboard config", False),
    # YouTube tokens (if exist)
    ("data/yt_token_channel1.json", "YouTube channel1 token", True),
    ("data/yt_token_channel2.json", "YouTube channel2 token", True),
    # Data
    ("data/duas.json", "Duas database", False),
    ("data/categories.json", "Categories database", False),
]

# Backup encryption key — derived from machine-specific secret
_BACKUP_KEY_ENV = "DUA_BACKUP_KEY"


def _get_backup_key():
    """Get or generate a Fernet key for backup encryption."""
    raw = os.environ.get(_BACKUP_KEY_ENV)
    if raw:
        return raw.encode() if isinstance(raw, str) else raw
    # Derive from project path + salt (stable per machine)
    salt_path = SECURITY_DIR / "salt.bin"
    seed = str(PROJECT).encode()
    if salt_path.exists():
        seed += salt_path.read_bytes()
    else:
        seed += b"dua-backup-fallback"
    import base64

    h = hashlib.sha256(seed).digest()
    return base64.urlsafe_b64encode(h)


def encrypt_backup_file(src_path, dst_path):
    """Encrypt a file for backup using Fernet."""
    from cryptography.fernet import Fernet

    key = _get_backup_key()
    cipher = Fernet(key)
    data = src_path.read_bytes()
    encrypted = cipher.encrypt(data)
    dst_path.write_bytes(encrypted)


def decrypt_backup_file(src_path):
    """Decrypt a backup file. Returns decrypted bytes."""
    from cryptography.fernet import Fernet

    key = _get_backup_key()
    cipher = Fernet(key)
    return cipher.decrypt(src_path.read_bytes())


def compute_checksum(file_path):
    """Compute SHA-256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception:
        return None


def create_backup():
    """Create timestamped backup. Sensitive files are encrypted."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"backup_{timestamp}"
    backup_path.mkdir(parents=True, exist_ok=True)

    backed_up = []
    checksums = {}
    encrypted = []
    for rel_path, description, do_encrypt in BACKUP_FILES:
        src = PROJECT / rel_path
        if src.exists():
            dst = backup_path / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            if do_encrypt:
                encrypt_backup_file(src, dst)
                encrypted.append(rel_path)
                backed_up.append(f"  ✓ {description}: {rel_path} [ENCRYPTED]")
            else:
                shutil.copy2(src, dst)
                backed_up.append(f"  ✓ {description}: {rel_path}")
            checksum = compute_checksum(dst)
            checksums[rel_path] = checksum
        else:
            backed_up.append(f"  - {description}: {rel_path} (not found)")

    # Save backup manifest
    manifest = {
        "timestamp": timestamp,
        "files": backed_up,
        "checksums": checksums,
        "encrypted": encrypted,
        "project": str(PROJECT),
    }
    (backup_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Backup created: {backup_path}")
    print("Files backed up:")
    for item in backed_up:
        print(item)

    return backup_path


def list_backups():
    """List available backups."""
    if not BACKUP_DIR.exists():
        print("No backups found.")
        return

    backups = sorted(BACKUP_DIR.iterdir())
    if not backups:
        print("No backups found.")
        return

    print("Available backups:")
    for backup in backups:
        if backup.is_dir():
            manifest = backup / "manifest.json"
            if manifest.exists():
                data = json.loads(manifest.read_text(encoding="utf-8"))
                print(f"  {backup.name} - {data['timestamp']}")
            else:
                print(f"  {backup.name}")


def _backup_dirs_sorted():
    """All backup directories ordered oldest first (by mtime, not name)."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(
        (d for d in BACKUP_DIR.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
    )


def rotate_backups(max_backups=10):
    """Keep only the most recent backups."""
    if not BACKUP_DIR.exists():
        return

    backups = _backup_dirs_sorted()
    if len(backups) <= max_backups:
        return

    to_delete = backups[: len(backups) - max_backups]
    for backup in to_delete:
        shutil.rmtree(backup)
        print(f"  Rotated old backup: {backup.name}")


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        list_backups()
    else:
        create_backup()
        rotate_backups()
