"""Path security validation for file operations.

Prevents path injection attacks by validating that user-provided paths
are within allowed directories and do not access sensitive system files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, List, Tuple

from utils.errors import PathSecurityError


# --------------------------------------------------------------------
# Default allowed directories (can be overridden via config)
# --------------------------------------------------------------------

# Common profiling data directories on Windows
DEFAULT_ALLOWED_DIRS_WINDOWS: List[str] = [
    os.path.expanduser("~"),  # User home directory
    os.path.expanduser("~/Documents"),
    os.path.expanduser("~/Downloads"),
    os.path.expanduser("~/Desktop"),
    "C:\\ProgramData",  # Common application data
    "D:\\",  # Secondary drive (common for data storage)
    "E:\\",
]

# Common profiling data directories on Linux/Unix
DEFAULT_ALLOWED_DIRS_UNIX: List[str] = [
    os.path.expanduser("~"),
    os.path.expanduser("~/data"),
    "/data",
    "/home",
    "/tmp",
    "/var/data",
]

# Blocked path patterns (case-insensitive)
BLOCKED_PATTERNS: List[str] = [
    # Windows system paths
    r"^[A-Za-z]:\\Windows\\",
    r"^[A-Za-z]:\\Program Files\\",
    r"^[A-Za-z]:\\Program Files \(x86\)\\",
    r"^[A-Za-z]:\\Users\\[^\\]+\\AppData\\Local\\Microsoft\\",
    r"^[A-Za-z]:\\Users\\[^\\]+\\AppData\\Roaming\\Microsoft\\",
    r"^[A-Za-z]:\\Users\\[^\\]+\\ntuser\.dat",
    r"^[A-Za-z]:\\Users\\[^\\]+\\NTUSER\.DAT",
    # Linux/Unix system paths
    r"^/etc/",
    r"^/root/",
    r"^/boot/",
    r"^/proc/",
    r"^/sys/",
    r"^/dev/",
    # Sensitive files
    r"passwd$",
    r"shadow$",
    r"sudoers$",
    r"\.ssh/",
    r"\.gnupg/",
    r"\.pem$",
    r"\.key$",
    r"id_rsa",
    r"id_dsa",
    r"id_ecdsa",
    r"id_ed25519",
]

# Blocked extensions (binary/sensitive files)
BLOCKED_EXTENSIONS: List[str] = [
    ".exe", ".dll", ".so", ".dylib",  # Executables and libraries
    ".sys", ".drv",  # System drivers
    ".pem", ".key", ".p12", ".pfx",  # Certificates and keys
]


def _get_default_allowed_dirs() -> List[str]:
    """Get platform-specific default allowed directories."""
    if os.name == "nt":
        return DEFAULT_ALLOWED_DIRS_WINDOWS
    return DEFAULT_ALLOWED_DIRS_UNIX


def _is_path_blocked(path: str) -> Tuple[bool, Optional[str]]:
    """Check if path matches any blocked pattern.

    Returns:
        (is_blocked, reason) tuple
    """
    normalized = os.path.normpath(path)

    # Check blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True, f"Path matches blocked pattern: {pattern}"

    # Check blocked extensions
    _, ext = os.path.splitext(normalized)
    if ext.lower() in BLOCKED_EXTENSIONS:
        return True, f"File extension '{ext}' is not allowed"

    return False, None


def _is_path_in_allowed_dir(path: str, allowed_dirs: List[str]) -> Tuple[bool, Optional[str]]:
    """Check if resolved path is within any allowed directory.

    Returns:
        (is_allowed, reason) tuple
    """
    try:
        resolved_path = Path(path).resolve()
    except (OSError, ValueError) as e:
        return False, f"Invalid path: {e}"

    for allowed_dir in allowed_dirs:
        try:
            allowed_path = Path(allowed_dir).resolve()
            # Check if resolved_path is a subdirectory of allowed_path
            try:
                resolved_path.relative_to(allowed_path)
                return True, None
            except ValueError:
                pass
        except (OSError, ValueError):
            continue

    return False, f"Path is not within any allowed directory"


def validate_path(
    path: str,
    allowed_dirs: Optional[List[str]] = None,
    must_exist: bool = False,
    allow_absolute_only: bool = True,
) -> str:
    """Validate a user-provided file path for security.

    Args:
        path: The file path to validate.
        allowed_dirs: List of allowed base directories. If None, uses defaults.
        must_exist: If True, also check that the path exists.
        allow_absolute_only: If True, reject relative paths.

    Returns:
        The normalized, validated path.

    Raises:
        PathSecurityError: If the path fails validation.
    """
    if not path or not path.strip():
        raise PathSecurityError("Path cannot be empty")

    path = path.strip()

    # Check for path traversal attempts BEFORE normalization
    # This catches ".." in the original input
    if ".." in path:
        raise PathSecurityError(
            f"Path traversal detected. '..' is not allowed in path: '{path}'"
        )

    # Normalize path separators
    normalized = os.path.normpath(path)

    # Check for absolute path requirement
    if allow_absolute_only and not os.path.isabs(normalized):
        raise PathSecurityError(
            f"Relative paths are not allowed. Please provide an absolute path. "
            f"Received: '{path}'"
        )

    # Check for blocked patterns
    is_blocked, reason = _is_path_blocked(normalized)
    if is_blocked:
        raise PathSecurityError(
            f"Access denied: {reason}. Path: '{path}'"
        )

    # Check against allowed directories
    dirs_to_check = allowed_dirs if allowed_dirs else _get_default_allowed_dirs()
    is_allowed, reason = _is_path_in_allowed_dir(normalized, dirs_to_check)
    if not is_allowed:
        raise PathSecurityError(
            f"Access denied: {reason}. "
            f"Allowed directories: {dirs_to_check}"
        )

    # Check existence if required
    if must_exist and not os.path.exists(normalized):
        raise PathSecurityError(f"Path does not exist: '{normalized}'")

    return normalized


def validate_file_path_for_import(
    file_path: str,
    allowed_dirs: Optional[List[str]] = None,
) -> str:
    """Validate a file path for trace file import.

    This is a convenience wrapper specifically for import operations.

    Args:
        file_path: The trace file path to validate.
        allowed_dirs: List of allowed base directories.

    Returns:
        The validated file path.

    Raises:
        PathSecurityError: If the path fails validation.
    """
    validated = validate_path(file_path, allowed_dirs, must_exist=True)

    # Additional check: ensure it's a file, not a directory
    if os.path.isdir(validated):
        raise PathSecurityError(
            f"Expected a file, but path is a directory: '{validated}'"
        )

    return validated


def validate_directory_path(
    dir_path: str,
    allowed_dirs: Optional[List[str]] = None,
) -> str:
    """Validate a directory path for listing operations.

    Args:
        dir_path: The directory path to validate.
        allowed_dirs: List of allowed base directories.

    Returns:
        The validated directory path.

    Raises:
        PathSecurityError: If the path fails validation.
    """
    validated = validate_path(dir_path, allowed_dirs, must_exist=True)

    # Additional check: ensure it's a directory
    if not os.path.isdir(validated):
        raise PathSecurityError(
            f"Expected a directory, but path is a file: '{validated}'"
        )

    return validated


def get_allowed_directories() -> List[str]:
    """Get the list of currently allowed directories.

    Returns:
        List of allowed directory paths.
    """
    return _get_default_allowed_dirs()
