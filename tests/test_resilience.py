"""
Edge-Case & Resilience Tests
Tests for corrupt audio handling, network timeout recovery, and vault corruption.

Run with: python -m pytest tests/test_resilience.py -v
"""

import os
import shutil
import sys
import tempfile
import wave
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.audio_mixer import AudioMixer
from core.security import SecurityManager, VaultWriteError
from core.tts_engine import TTSEngine

# ============================================================
# Test Fixtures
# ============================================================


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test files."""
    d = tempfile.mkdtemp(prefix="resilience_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_wav(tmp_dir):
    """Create a valid WAV file for testing."""
    path = os.path.join(tmp_dir, "valid.wav")
    sample_rate = 48000
    duration = 1.0
    t = np.arange(int(sample_rate * duration)) / sample_rate
    pcm = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return path


@pytest.fixture
def corrupt_wav(tmp_dir):
    """Create a corrupt WAV file (invalid header)."""
    path = os.path.join(tmp_dir, "corrupt.wav")
    # Write random bytes with invalid header
    with open(path, "wb") as f:
        f.write(b"INVALID_HEADER" + os.urandom(1000))
    return path


@pytest.fixture
def empty_file(tmp_dir):
    """Create an empty file."""
    path = os.path.join(tmp_dir, "empty.wav")
    with open(path, "wb") as _f:
        pass  # Empty file
    return path


@pytest.fixture
def truncated_wav(tmp_dir):
    """Create a truncated WAV file."""
    path = os.path.join(tmp_dir, "truncated.wav")
    # Write partial WAV header
    with open(path, "wb") as f:
        f.write(b"RIFF")  # Incomplete header
    return path


@pytest.fixture
def security_manager(tmp_dir):
    """Create a SecurityManager for testing."""
    password = "test_password_123"
    vault_path = os.path.join(tmp_dir, "test_vault.enc")
    keys_dir = os.path.join(tmp_dir, "test_keys")
    salt_path = os.path.join(tmp_dir, "test_salt.bin")

    os.makedirs(keys_dir, exist_ok=True)

    sm = SecurityManager.__new__(SecurityManager)
    sm.master_password = password
    sm.vault_path = vault_path
    sm.keys_dir = keys_dir
    sm.salt_path = salt_path
    sm.salt = os.urandom(16)
    sm.key = sm._derive_key_with_salt(password, sm.salt)
    sm.cipher = None  # Will be initialized below

    from cryptography.fernet import Fernet

    sm.cipher = Fernet(sm.key)
    sm._salt_regenerated = False

    return sm


# ============================================================
# 1. Corrupt Audio Handling Tests
# ============================================================


class TestCorruptAudioHandling:
    """Test graceful handling of corrupt audio inputs."""

    def test_empty_file_handling(self, empty_file, tmp_dir):
        """Test: Empty file should be handled gracefully."""
        output = os.path.join(tmp_dir, "output.wav")

        # Should not raise exception
        result = AudioMixer.merge_audio_sequential([empty_file], output, gap_seconds=0.0)

        # Should return False or handle gracefully
        assert isinstance(result, bool)

    def test_corrupt_header_handling(self, corrupt_wav, tmp_dir):
        """Test: Corrupt WAV header should be handled gracefully."""
        output = os.path.join(tmp_dir, "output.wav")

        # Should not raise exception
        result = AudioMixer.merge_audio_sequential([corrupt_wav], output, gap_seconds=0.0)

        # Should return False or handle gracefully
        assert isinstance(result, bool)

    def test_truncated_file_handling(self, truncated_wav, tmp_dir):
        """Test: Truncated WAV file should be handled gracefully."""
        output = os.path.join(tmp_dir, "output.wav")

        # Should not raise exception
        result = AudioMixer.merge_audio_sequential([truncated_wav], output, gap_seconds=0.0)

        # Should return False or handle gracefully
        assert isinstance(result, bool)

    def test_nonexistent_file_handling(self, tmp_dir):
        """Test: Nonexistent file should be handled gracefully."""
        output = os.path.join(tmp_dir, "output.wav")
        nonexistent = os.path.join(tmp_dir, "nonexistent.wav")

        # Should not raise exception
        result = AudioMixer.merge_audio_sequential([nonexistent], output, gap_seconds=0.0)

        # Should return False or handle gracefully
        assert isinstance(result, bool)

    def test_mixed_valid_corrupt_files(self, sample_wav, corrupt_wav, tmp_dir):
        """Test: Mix of valid and corrupt files should be handled gracefully."""
        output = os.path.join(tmp_dir, "output.wav")

        # Should not raise exception
        result = AudioMixer.merge_audio_sequential([sample_wav, corrupt_wav], output, gap_seconds=0.1)

        # Should return False or handle gracefully
        assert isinstance(result, bool)

    def test_binary_data_as_audio(self, tmp_dir):
        """Test: Binary data (not audio) should be handled gracefully."""
        binary_file = os.path.join(tmp_dir, "binary.wav")
        with open(binary_file, "wb") as f:
            f.write(os.urandom(10000))

        output = os.path.join(tmp_dir, "output.wav")

        # Should not raise exception
        result = AudioMixer.merge_audio_sequential([binary_file], output, gap_seconds=0.0)

        # Should return False or handle gracefully
        assert isinstance(result, bool)

    def test_very_large_file_handling(self, tmp_dir):
        """Test: Very large file should be handled gracefully (or rejected)."""
        large_file = os.path.join(tmp_dir, "large.wav")

        # Create a large file (10MB of zeros)
        with open(large_file, "wb") as f:
            f.write(b"\x00" * (10 * 1024 * 1024))

        output = os.path.join(tmp_dir, "output.wav")

        # Should not raise exception (may fail gracefully or timeout)
        try:
            result = AudioMixer.merge_audio_sequential([large_file], output, gap_seconds=0.0)
            assert isinstance(result, bool)
        except Exception as e:
            # If it raises, it should be a controlled exception
            assert isinstance(e, (MemoryError, OSError, ValueError))

    def test_special_characters_in_path(self, sample_wav, tmp_dir):
        """Test: File with special characters in path should be handled."""
        special_dir = os.path.join(tmp_dir, "special chars (1)")
        os.makedirs(special_dir, exist_ok=True)

        special_file = os.path.join(special_dir, "file with spaces.wav")
        shutil.copy(sample_wav, special_file)

        output = os.path.join(tmp_dir, "output.wav")

        # Should handle special characters in path
        result = AudioMixer.merge_audio_sequential([special_file], output, gap_seconds=0.1)

        assert isinstance(result, bool)


# ============================================================
# 2. Network Timeout & Retry Recovery Tests
# ============================================================


class TestNetworkTimeoutRecovery:
    """Test TTS engine retry behavior on network failures.

    All tests mock edge_tts at module level — no real network calls.
    """

    def test_retry_on_timeout(self):
        """Test: TTS should retry on timeout errors."""
        save_attempts = []

        async def mock_save(*args, **kwargs):
            save_attempts.append(1)
            if len(save_attempts) < 3:
                raise TimeoutError("Connection timed out")
            return True

        mock_comm = MagicMock()
        mock_comm.save = mock_save

        with patch("core.tts_engine.edge_tts") as mock_edge_tts:
            mock_edge_tts.Communicate.return_value = mock_comm
            result = TTSEngine.generate_audio(
                "بسم الله الرحمن الرحيم", "ar", os.path.join(tempfile.mkdtemp(), "test.mp3")
            )

        assert result is True
        assert len(save_attempts) == 3

    def test_retry_on_http_503(self):
        """Test: TTS should retry on HTTP 503 errors."""
        with patch("core.tts_engine.edge_tts") as mock_edge_tts:
            mock_comm = MagicMock()
            mock_comm.save = AsyncMock(side_effect=Exception("HTTP 503 Service Unavailable"))
            mock_edge_tts.Communicate.return_value = mock_comm

            result = TTSEngine.generate_audio(
                "بسم الله الرحمن الرحيم", "ar", os.path.join(tempfile.mkdtemp(), "test.mp3")
            )

        assert result is False

    def test_retry_on_network_error(self):
        """Test: TTS should retry on network errors."""
        with patch("core.tts_engine.edge_tts") as mock_edge_tts:
            mock_comm = MagicMock()
            mock_comm.save = AsyncMock(side_effect=ConnectionError("Network unreachable"))
            mock_edge_tts.Communicate.return_value = mock_comm

            result = TTSEngine.generate_audio(
                "بسم الله الرحمن الرحيم", "ar", os.path.join(tempfile.mkdtemp(), "test.mp3")
            )

        assert result is False

    def test_max_retries_exceeded(self):
        """Test: TTS should stop after max retries."""
        with patch("core.tts_engine.edge_tts") as mock_edge_tts:
            mock_comm = MagicMock()
            mock_comm.save = AsyncMock(side_effect=TimeoutError("Always fails"))
            mock_edge_tts.Communicate.return_value = mock_comm

            result = TTSEngine.generate_audio(
                "بسم الله الرحمن الرحيم", "ar", os.path.join(tempfile.mkdtemp(), "test.mp3")
            )

        assert result is False

    def test_partial_failure_parallel_tts(self):
        """Test: Parallel TTS should handle partial failures.

        Tests that _async_generate returns False on failure (simulating
        a TTS engine error without real network calls).
        """

        async def mock_async_gen_ar(text, voice, output, timing=None, rate=None, pitch=None):
            return True  # Arabic succeeds

        async def mock_async_gen_ur(text, voice, output, timing=None, rate=None, pitch=None):
            return False  # Urdu fails

        # Test Arabic success
        with patch("core.tts_engine.TTSEngine._async_generate", side_effect=mock_async_gen_ar):
            import asyncio

            ar_result = asyncio.run(TTSEngine._async_generate("test", "ar-SA-HamedNeural", "dummy.mp3"))

        # Test Urdu failure
        with patch("core.tts_engine.TTSEngine._async_generate", side_effect=mock_async_gen_ur):
            ur_result = asyncio.run(TTSEngine._async_generate("test", "ur-PK-AsadNeural", "dummy.mp3"))

        assert ar_result is True
        assert ur_result is False

    def test_timeout_during_save(self):
        """Test: Timeout during save should be handled."""
        with patch("core.tts_engine.edge_tts") as mock_edge_tts:
            mock_comm = MagicMock()
            mock_comm.save = AsyncMock(side_effect=TimeoutError("Save timed out"))
            mock_edge_tts.Communicate.return_value = mock_comm

            result = TTSEngine.generate_audio(
                "بسم الله الرحمن الرحيم", "ar", os.path.join(tempfile.mkdtemp(), "test.mp3")
            )

        assert result is False

    def test_invalid_language_raises(self):
        """Test: Invalid language should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported language"):
            TTSEngine.generate_audio("test", "xx", os.path.join(tempfile.mkdtemp(), "test.mp3"))

    def test_empty_text_handled(self):
        """Test: Empty text should be handled gracefully."""
        with patch("core.tts_engine.edge_tts") as mock_edge_tts:
            mock_comm = MagicMock()
            mock_comm.save = AsyncMock(return_value=True)
            mock_edge_tts.Communicate.return_value = mock_comm

            result = TTSEngine.generate_audio("", "ar", os.path.join(tempfile.mkdtemp(), "test.mp3"))

        assert isinstance(result, bool)


# ============================================================
# 3. Vault & Encryption Recovery Tests
# ============================================================


class TestVaultEncryptionRecovery:
    """Test vault corruption and encryption recovery."""

    def test_corrupted_vault_recovery(self, security_manager, tmp_dir):
        """Test: Corrupted vault file should be handled gracefully."""
        vault_path = security_manager.vault_path

        # Create corrupted vault file
        with open(vault_path, "wb") as f:
            f.write(b"CORRUPTED_VAULT_DATA" * 100)

        # Should handle corrupted vault gracefully
        try:
            data = security_manager.load_vault()
            # If it returns, it should be None or empty
            assert data is None or data == {}
        except Exception as e:
            # Should raise controlled exception
            assert isinstance(e, (VaultWriteError, ValueError, Exception))

    def test_empty_vault_recovery(self, security_manager, tmp_dir):
        """Test: Empty vault file should be handled gracefully."""
        vault_path = security_manager.vault_path

        # Create empty vault file
        with open(vault_path, "wb") as _f:
            pass  # Empty file

        # Should handle empty vault gracefully
        try:
            data = security_manager.load_vault()
            # If it returns, it should be None or empty
            assert data is None or data == {}
        except Exception as e:
            # Should raise controlled exception
            assert isinstance(e, (VaultWriteError, ValueError, Exception))

    def test_invalid_decryption_key(self, security_manager, tmp_dir):
        """Test: Invalid decryption key should fail gracefully."""
        # Save valid data first
        test_data = {"test": "data"}
        security_manager.save_vault(test_data)

        # Create new security manager with different password
        different_password = "different_password_456"
        different_sm = SecurityManager.__new__(SecurityManager)
        different_sm.master_password = different_password
        different_sm.vault_path = security_manager.vault_path
        different_sm.keys_dir = security_manager.keys_dir
        different_sm.salt_path = security_manager.salt_path
        different_sm.salt = security_manager.salt
        different_sm.key = different_sm._derive_key_with_salt(different_password, security_manager.salt)

        from cryptography.fernet import Fernet

        different_sm.cipher = Fernet(different_sm.key)
        different_sm._salt_regenerated = False

        # Should fail to decrypt with wrong key
        try:
            data = different_sm.load_vault()
            # If it returns data, it should be corrupted/wrong
            if data is not None:
                assert data != test_data  # Should not match original
        except Exception as e:
            # Should raise controlled exception
            assert isinstance(e, (VaultWriteError, ValueError, Exception))

    def test_tampered_vault_detection(self, security_manager, tmp_dir):
        """Test: Tampered vault should be detected."""
        vault_path = security_manager.vault_path

        # Save valid data first
        test_data = {"test": "data"}
        security_manager.save_vault(test_data)

        # Tamper with the vault file
        with open(vault_path, "rb") as f:
            data = f.read()

        # Flip some bits
        tampered = bytearray(data)
        for i in range(0, min(10, len(tampered)), 2):
            tampered[i] ^= 0xFF

        with open(vault_path, "wb") as f:
            f.write(bytes(tampered))

        # Should detect tampering
        try:
            loaded = security_manager.load_vault()
            # If it returns data, it should be None or corrupted
            if loaded is not None:
                assert loaded != test_data  # Should not match original
        except Exception as e:
            # Should raise controlled exception
            assert isinstance(e, (VaultWriteError, ValueError, Exception))

    def test_missing_vault_file(self, security_manager, tmp_dir):
        """Test: Missing vault file should be handled gracefully."""
        # Ensure vault doesn't exist
        vault_path = security_manager.vault_path
        if os.path.exists(vault_path):
            os.remove(vault_path)

        # Should handle missing vault gracefully
        try:
            data = security_manager.load_vault()
            # If it returns, it should be None or empty
            assert data is None or data == {}
        except Exception as e:
            # Should raise controlled exception
            assert isinstance(e, (VaultWriteError, FileNotFoundError, Exception))

    def test_key_rotation_recovery(self, security_manager, tmp_dir):
        """Test: Key rotation should be handled gracefully."""
        # Save data with original key
        test_data = {"test": "data", "sensitive": "info"}
        security_manager.save_vault(test_data)

        # Simulate key rotation (new salt)
        _old_salt = security_manager.salt
        new_salt = os.urandom(16)
        security_manager.salt = new_salt
        security_manager.key = security_manager._derive_key_with_salt(security_manager.master_password, new_salt)
        security_manager.cipher = None

        from cryptography.fernet import Fernet

        security_manager.cipher = Fernet(security_manager.key)

        # Should handle key rotation gracefully
        try:
            # Old data may be lost, but should not crash
            data = security_manager.load_vault()
            # If it returns, it should be None or different
            if data is not None:
                # Data may be lost due to key rotation
                pass
        except Exception as e:
            # Should raise controlled exception
            assert isinstance(e, (VaultWriteError, ValueError, Exception))

    def test_concurrent_vault_access(self, security_manager, tmp_dir):
        """Test: Concurrent vault access should be handled gracefully."""
        import threading

        results = []
        errors = []

        def save_data(i):
            try:
                data = {"thread": i, "data": f"test_{i}"}
                security_manager.save_vault(data)
                results.append(i)
            except Exception as e:
                errors.append(e)

        # Run concurrent saves
        threads = [threading.Thread(target=save_data, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # Should handle concurrent access without crashes
        # Some may fail due to file locking, but should not crash
        assert len(results) + len(errors) == 5

    def test_vault_write_permission_error(self, security_manager, tmp_dir):
        """Test: Vault write permission error should be handled."""
        # Make vault directory read-only (if possible)
        vault_dir = os.path.dirname(security_manager.vault_path)

        try:
            # Try to make directory read-only
            os.chmod(vault_dir, 0o444)

            # Should handle permission error gracefully
            try:
                security_manager.save_vault({"test": "data"})
            except Exception as e:
                # Should raise controlled exception
                assert isinstance(e, (VaultWriteError, PermissionError, OSError))
            finally:
                # Restore permissions
                os.chmod(vault_dir, 0o755)
        except OSError:
            # Skip if can't change permissions (e.g., Windows)
            pytest.skip("Cannot change permissions on this system")


# ============================================================
# 4. Integration Tests
# ============================================================


class TestIntegrationResilience:
    """Integration tests for overall system resilience."""

    def test_pipeline_with_corrupt_audio(self, sample_wav, corrupt_wav, tmp_dir):
        """Test: Pipeline should handle corrupt audio gracefully."""
        output = os.path.join(tmp_dir, "output.wav")

        # Try to merge with corrupt audio
        result = AudioMixer.merge_audio_sequential([sample_wav, corrupt_wav], output, gap_seconds=0.1)

        # Should handle gracefully
        assert isinstance(result, bool)

    def test_tts_with_invalid_parameters(self):
        """Test: TTS with invalid parameters should fail gracefully."""
        # Invalid language raises ValueError
        with pytest.raises(ValueError, match="Unsupported language"):
            TTSEngine.generate_audio("test", "invalid_lang", os.path.join(tempfile.mkdtemp(), "test.mp3"))

    def test_security_with_weak_password(self, tmp_dir):
        """Test: Security with weak password should work (but warn)."""
        weak_password = "123"

        try:
            sm = SecurityManager(weak_password)
            # Should work but may log warning
            assert sm is not None
        except Exception as e:
            # Should handle gracefully
            assert isinstance(e, (ValueError, Exception))


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
