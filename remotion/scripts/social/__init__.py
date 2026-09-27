"""Shared helpers for multi-platform uploads (Phase 1 foundation).

Modules
-------
state : unified upload-state ledger shared by every platform uploader.
captions : per-platform caption formatting (Phase 2).

This package holds platform-independent logic only. Platform wire protocols
live in the per-platform modules (tiktok_upload, instagram_upload,
facebook_upload) and YouTube stays in remotion/scripts/upload_shorts.py.
"""

__all__ = ["state"]
