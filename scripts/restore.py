"""
Restore Script for Dua Video Generator
Restores vault, salt, tokens, and critical config files from backup.
"""

import contextlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
BACKUP_DIR = PROJECT / "backups"


def _load_backup_module():
    """Import backup helpers (BACKUP_FILES, decrypt) from scripts/backup."""
    sys.path.insert(0, str(PROJECT / "scripts"))
    try:
        from backup import BACKUP_FILES, decrypt_backup_file

        return BACKUP_FILES, decrypt_backup_file
    except ImportError:
        return None, None


def auto_backup():
    """Create automatic backup before restore."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"pre_restore_{timestamp}"
    backup_path.mkdir(parents=True, exist_ok=True)

    # Import backup files list from backup module
    BACKUP_FILES, _ = _load_backup_module()
    if BACKUP_FILES is None:
        BACKUP_FILES = [
            ("security/salt.bin", "Security salt", False),
            ("remotion/dashboard/auth.json", "Dashboard auth token", True),
            ("remotion/dashboard/config.json", "Dashboard config", False),
            ("data/duas.json", "Duas database", False),
        ]

    backed_up = 0
    for rel_path, _description, _encrypt in BACKUP_FILES:
        src = PROJECT / rel_path
        if src.exists():
            dst = backup_path / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            backed_up += 1

    # Save manifest
    manifest = {"timestamp": timestamp, "type": "pre_restore", "files_count": backed_up}
    (backup_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Auto-backup created: {backup_path.name} ({backed_up} files)")
    return backup_path


def restore_backup(backup_name=None, force=False, target=None):
    """Restore from a backup. If no name given, restore latest.
    If target given, restore into that directory instead of PROJECT
    (used for safe test-restores; no auto-backup is created in that case).
    """
    if not BACKUP_DIR.exists():
        print("No backups directory found.")
        return False

    if backup_name:
        backup_path = BACKUP_DIR / backup_name
    else:
        # Find latest backup (by mtime, not name - name sort would pick
        # v010_/pre_restore_ dirs which are not real timestamped backups)
        backups = sorted(
            (d for d in BACKUP_DIR.iterdir() if d.is_dir()),
            key=lambda d: d.stat().st_mtime,
        )
        if not backups:
            print("No backups found.")
            return False
        backup_path = backups[-1]

    if not backup_path.exists():
        print(f"Backup not found: {backup_path}")
        return False

    # Load manifest
    manifest_path = backup_path / "manifest.json"
    encrypted_files = set()
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"Restoring from: {manifest['timestamp']}")
        encrypted_files = set(manifest.get("encrypted", []))
        files_to_restore = manifest.get("files", [])
        for item in files_to_restore:
            print(f"  - {item}")
    else:
        print(f"Restoring from: {backup_path.name}")

    _, decrypt_func = _load_backup_module()

    dst_root = Path(target) if target else PROJECT

    # Confirmation prompt
    if not force and target is None:
        file_count = len([f for f in backup_path.rglob("*") if f.is_file() and f.name != "manifest.json"])
        print(f"\nThis will overwrite {file_count} files in the project.")
        confirm = input("Are you sure? (y/N): ").strip().lower()
        if confirm != "y":
            print("Restore cancelled.")
            return False

    # Auto-backup current state before restore (real restores only)
    if target is None:
        print("\nCreating auto-backup of current state...")
        auto_backup()

    # Restore files
    restored = 0
    for item in backup_path.rglob("*"):
        if item.is_file() and item.name != "manifest.json":
            rel = item.relative_to(backup_path).as_posix()
            dst = dst_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if rel in encrypted_files and decrypt_func is not None:
                data = decrypt_func(item)
                dst.write_bytes(data)
                print(f"  Restored: {rel} [decrypted]")
            elif rel in encrypted_files:
                print(f"  WARN: {rel} marked encrypted but decrypt unavailable - copied raw")
                shutil.copy2(item, dst)
            else:
                shutil.copy2(item, dst)
                print(f"  Restored: {rel}")
            restored += 1

    print(f"\nRestored {restored} files.")
    return True


def list_backups():
    """List available backups."""
    if not BACKUP_DIR.exists():
        print("No backups found.")
        return

    backups = sorted(
        (d for d in BACKUP_DIR.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
    )
    if not backups:
        print("No backups found.")
        return

    print("Available backups:")
    for backup in backups:
        manifest = backup / "manifest.json"
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            print(f"  {backup.name} - {data['timestamp']}")
        else:
            print(f"  {backup.name}")


if __name__ == "__main__":
    import argparse

    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(prog="restore.py")
    ap.add_argument("command", nargs="?", default="list", help="list | restore")
    ap.add_argument("backup_name", nargs="?", default=None, help="backup directory name (optional)")
    ap.add_argument("--yes", action="store_true", help="restore without confirmation")
    ap.add_argument(
        "--to", default=None, help="restore into this target directory instead of the project (safe test-restore)"
    )
    args = ap.parse_args()

    if args.command == "list":
        list_backups()
    elif args.command == "restore":
        restore_backup(args.backup_name, force=args.yes, target=args.to)
    else:
        print("Usage:")
        print("  python restore.py list                    - List backups")
        print("  python restore.py restore [name] [--yes]  - Restore from backup")
        print("  python restore.py restore [name] --to DIR - Safe test-restore")
        print("  python restore.py restore --to DIR --yes  - Both")
