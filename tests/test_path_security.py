"""Unit tests for path security validation."""

import os
import pytest

from utils.path_security import (
    validate_path,
    validate_file_path_for_import,
    validate_directory_path,
    get_allowed_directories,
    PathSecurityError,
)


class TestValidatePath:
    """Tests for the validate_path function."""

    def test_empty_path_raises_error(self):
        """Empty path should raise PathSecurityError."""
        with pytest.raises(PathSecurityError, match="cannot be empty"):
            validate_path("")

    def test_whitespace_path_raises_error(self):
        """Whitespace-only path should raise PathSecurityError."""
        with pytest.raises(PathSecurityError, match="cannot be empty"):
            validate_path("   ")

    def test_relative_path_rejected_when_absolute_required(self):
        """Relative paths should be rejected when allow_absolute_only=True."""
        # Relative paths without .. are rejected with "Relative paths" message
        with pytest.raises(PathSecurityError, match="Relative paths are not allowed"):
            validate_path("some/path", allow_absolute_only=True)

    def test_relative_path_with_traversal_rejected(self):
        """Relative paths with .. are rejected as path traversal."""
        # Relative paths with .. are rejected as path traversal (more severe)
        with pytest.raises(PathSecurityError, match="Path traversal detected"):
            validate_path("../some/path", allow_absolute_only=True)

    def test_path_traversal_detected(self):
        """Path traversal attempts should be detected and blocked."""
        # This test uses a path with .. that resolves to a non-blocked location
        # Note: On Windows, C:\Users\..\Windows\System32 would be blocked by
        # the Windows system path pattern first, so we use a different example
        if os.name == "nt":
            # Use a path that has .. but doesn't hit blocked patterns
            traversal_path = "C:\\Data\\..\\OtherData\\file.json"
            # This should be blocked by path traversal detection
            with pytest.raises(PathSecurityError, match="Path traversal detected"):
                validate_path(traversal_path, allowed_dirs=["C:\\Data"])
        else:
            traversal_path = "/home/user/../other/file.json"
            with pytest.raises(PathSecurityError, match="Path traversal detected"):
                validate_path(traversal_path, allowed_dirs=["/home/user"])

    def test_blocked_windows_system_path(self):
        """Windows system paths should be blocked."""
        if os.name != "nt":
            pytest.skip("Windows-specific test")

        with pytest.raises(PathSecurityError, match="blocked pattern"):
            validate_path("C:\\Windows\\System32\\config\\SAM", allowed_dirs=["C:\\"])

    def test_blocked_linux_etc_path(self):
        """Linux /etc paths should be blocked."""
        if os.name == "nt":
            pytest.skip("Linux-specific test")

        with pytest.raises(PathSecurityError, match="blocked pattern"):
            validate_path("/etc/passwd", allowed_dirs=["/"])

    def test_blocked_ssh_key_path(self):
        """SSH key paths should be blocked."""
        if os.name == "nt":
            path = "C:\\Users\\test\\.ssh\\id_rsa"
        else:
            path = "/home/test/.ssh/id_rsa"

        with pytest.raises(PathSecurityError, match="blocked pattern"):
            validate_path(path, allowed_dirs=[os.path.expanduser("~")])

    def test_blocked_executable_extension(self):
        """Executable file extensions should be blocked."""
        if os.name == "nt":
            path = "C:\\Users\\test\\malware.exe"
        else:
            path = "/home/test/malware.exe"

        with pytest.raises(PathSecurityError, match="not allowed"):
            validate_path(path, allowed_dirs=[os.path.dirname(path)])

    def test_valid_path_in_allowed_directory(self, tmp_path):
        """Valid paths within allowed directories should pass."""
        allowed_dir = str(tmp_path)
        test_file = tmp_path / "test.json"
        test_file.write_text("{}")

        result = validate_path(str(test_file), allowed_dirs=[allowed_dir], must_exist=True)
        assert result == str(test_file.resolve())

    def test_path_outside_allowed_directory(self, tmp_path):
        """Paths outside allowed directories should be rejected."""
        allowed_dir = str(tmp_path)
        outside_path = tmp_path.parent / "outside.json"

        with pytest.raises(PathSecurityError, match="not within any allowed directory"):
            validate_path(str(outside_path), allowed_dirs=[allowed_dir])

    def test_nonexistent_path_when_must_exist_true(self, tmp_path):
        """Non-existent paths should fail when must_exist=True."""
        allowed_dir = str(tmp_path)
        nonexistent = tmp_path / "nonexistent.json"

        with pytest.raises(PathSecurityError, match="does not exist"):
            validate_path(str(nonexistent), allowed_dirs=[allowed_dir], must_exist=True)

    def test_nonexistent_path_when_must_exist_false(self, tmp_path):
        """Non-existent paths should pass when must_exist=False."""
        allowed_dir = str(tmp_path)
        nonexistent = tmp_path / "nonexistent.json"

        result = validate_path(str(nonexistent), allowed_dirs=[allowed_dir], must_exist=False)
        assert result == str(nonexistent.resolve())


class TestValidateFilePathForImport:
    """Tests for the validate_file_path_for_import function."""

    def test_directory_path_rejected(self, tmp_path):
        """Directory paths should be rejected for file import."""
        allowed_dir = str(tmp_path)

        with pytest.raises(PathSecurityError, match="Expected a file, but path is a directory"):
            validate_file_path_for_import(str(tmp_path), allowed_dirs=[allowed_dir])

    def test_valid_file_path_passes(self, tmp_path):
        """Valid file paths should pass validation."""
        allowed_dir = str(tmp_path)
        test_file = tmp_path / "trace.json"
        test_file.write_text("{}")

        result = validate_file_path_for_import(str(test_file), allowed_dirs=[allowed_dir])
        assert result == str(test_file.resolve())


class TestValidateDirectoryPath:
    """Tests for the validate_directory_path function."""

    def test_file_path_rejected(self, tmp_path):
        """File paths should be rejected for directory validation."""
        allowed_dir = str(tmp_path)
        test_file = tmp_path / "test.json"
        test_file.write_text("{}")

        with pytest.raises(PathSecurityError, match="Expected a directory, but path is a file"):
            validate_directory_path(str(test_file), allowed_dirs=[allowed_dir])

    def test_valid_directory_path_passes(self, tmp_path):
        """Valid directory paths should pass validation."""
        allowed_dir = str(tmp_path.parent)
        test_dir = tmp_path / "subdir"
        test_dir.mkdir()

        result = validate_directory_path(str(test_dir), allowed_dirs=[allowed_dir])
        assert result == str(test_dir.resolve())


class TestGetAllowedDirectories:
    """Tests for the get_allowed_directories function."""

    def test_returns_list(self):
        """Should return a list of directories."""
        dirs = get_allowed_directories()
        assert isinstance(dirs, list)
        assert len(dirs) > 0

    def test_includes_home_directory(self):
        """Should include the user's home directory."""
        dirs = get_allowed_directories()
        home = os.path.expanduser("~")
        assert home in dirs


class TestPathSecurityError:
    """Tests for the PathSecurityError exception."""

    def test_message_attribute(self):
        """PathSecurityError should have a message attribute."""
        error = PathSecurityError("Test error message")
        assert error.message == "Test error message"
        assert str(error) == "Test error message"
