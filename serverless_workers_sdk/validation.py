"""
Input validation utilities for security and data integrity.

Provides comprehensive validation for:
- File paths (directory traversal prevention)
- User input (injection prevention)
- Command arguments (shell injection prevention)
- URLs and network inputs
- Request payloads
"""

import re
from typing import Optional, List, Tuple
from pathlib import Path


# =============================================================================
# File Path Validation
# =============================================================================

def validate_file_path(path: str, allow_absolute: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Validate a file path to prevent directory traversal and injection attacks.
    
    Args:
        path: The file path to validate.
        allow_absolute: Whether to allow absolute paths (default: False).
        
    Returns:
        Tuple of (is_valid, error_message).
        If valid, error_message is None.
        
    Examples:
        >>> validate_file_path("code/main.py")
        (True, None)
        
        >>> validate_file_path("../etc/passwd")
        (False, "Directory traversal detected")
    """
    if not path:
        return False, "Path cannot be empty"
    
    # Check for null bytes
    if "\x00" in path:
        return False, "Null bytes not allowed in path"
    
    # Check for absolute paths if not allowed
    if not allow_absolute and (path.startswith("/") or path.startswith("\\")):
        return False, "Absolute paths not allowed"
    
    # Check for directory traversal
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part == "..":
            return False, "Directory traversal detected"
        if part in ("", "."):
            continue
    
    # Check for shell metacharacters
    shell_chars = re.compile(r'[;&|`$(){}!\[\]<>]')
    if shell_chars.search(path):
        return False, "Shell metacharacters not allowed in path"
    
    # Check for suspicious patterns
    suspicious_patterns = [
        r"\.\./",  # Parent directory
        r"\.\.\\",  # Parent directory (Windows)
        r"/etc/",  # System directories
        r"/proc/",
        r"/sys/",
        r"\\windows\\",
    ]
    for pattern in suspicious_patterns:
        if re.search(pattern, path, re.IGNORECASE):
            return False, f"Suspicious path pattern detected: {pattern}"
    
    # Check path length
    if len(path) > 1024:
        return False, "Path too long (max 1024 characters)"
    
    return True, None


def validate_directory_path(path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate a directory path.
    
    Similar to validate_file_path but allows trailing slashes.
    
    Args:
        path: The directory path to validate.
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    # Remove trailing slash for validation
    clean_path = path.rstrip("/\\")
    return validate_file_path(clean_path)


def safe_path_join(base: Path, *parts: str) -> Optional[Path]:
    """
    Safely join path components, ensuring result stays within base.
    
    Args:
        base: The base directory that should contain the result.
        *parts: Path components to join.
        
    Returns:
        The resolved path if it stays within base, None otherwise.
        
    Example:
        >>> base = Path("/sandbox/user1")
        >>> safe_path_join(base, "code", "main.py")
        Path("/sandbox/user1/code/main.py")
        
        >>> safe_path_join(base, "..", "etc", "passwd")
        None
    """
    try:
        # Start with base path
        result = base.resolve()
        
        for part in parts:
            # Validate each part
            is_valid, error = validate_file_path(part)
            if not is_valid:
                return None
            
            # Join and resolve
            result = (result / part).resolve()
        
        # Verify final path is still under base
        base_resolved = base.resolve()
        try:
            result.relative_to(base_resolved)
            return result
        except ValueError:
            # Path is outside base
            return None
            
    except Exception:
        return None


# =============================================================================
# Command and Argument Validation
# =============================================================================

def validate_command(command: str, allowed_commands: Optional[List[str]] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate a command to prevent shell injection.
    
    Args:
        command: The command to validate.
        allowed_commands: List of allowed command names.
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    if not command:
        return False, "Command cannot be empty"
    
    # Check for shell metacharacters
    shell_chars = re.compile(r'[;&|`$(){}!\[\]<>\\]')
    if shell_chars.search(command):
        return False, "Shell metacharacters not allowed in command"
    
    # Check for newlines
    if "\n" in command or "\r" in command:
        return False, "Newlines not allowed in command"
    
    # Check against allowed commands if provided
    if allowed_commands:
        # Extract base command (first word)
        base_command = command.split()[0].lower()
        if base_command not in [c.lower() for c in allowed_commands]:
            return False, f"Command not allowed. Allowed: {', '.join(allowed_commands)}"
    
    # Check path traversal in command
    if ".." in command:
        return False, "Directory traversal not allowed in command"
    
    return True, None


def validate_command_arg(arg: str) -> Tuple[bool, Optional[str]]:
    """
    Validate a command argument.
    
    Args:
        arg: The argument to validate.
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    if not arg:
        return True, None  # Empty args are OK (will be filtered)
    
    # Check for shell metacharacters
    shell_chars = re.compile(r'[;&|`$(){}!\[\]<>\\]')
    if shell_chars.search(arg):
        return False, "Shell metacharacters not allowed in arguments"
    
    # Check for newlines
    if "\n" in arg or "\r" in arg:
        return False, "Newlines not allowed in arguments"
    
    # Check path traversal
    if ".." in arg:
        return False, "Directory traversal not allowed in arguments"
    
    # Check length
    if len(arg) > 4096:
        return False, "Argument too long (max 4096 characters)"
    
    return True, None


def validate_code_input(code: str, language: str = "python") -> Tuple[bool, Optional[str]]:
    """
    Validate code input for execution.
    
    Args:
        code: The code to validate.
        language: The programming language (python, node, etc.).
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    if not code:
        return False, "Code cannot be empty"
    
    # Check length
    if len(code) > 100000:  # 100KB limit
        return False, "Code too large (max 100KB)"
    
    # Check for dangerous patterns (language-specific)
    if language == "python":
        dangerous_patterns = [
            r"__import__\s*\(",
            r"eval\s*\(",
            r"exec\s*\(",
            r"compile\s*\(",
            r"open\s*\([^)]*[\"'][^\"']*[\"']\s*,\s*[\"'][rw]",
            r"os\.",
            r"sys\.",
            r"subprocess\.",
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, code):
                return False, f"Dangerous pattern detected: {pattern}"
    
    elif language == "javascript":
        dangerous_patterns = [
            r"eval\s*\(",
            r"Function\s*\(",
            r"require\s*\(['\"]child_process['\"]\)",
            r"require\s*\(['\"]fs['\"]\)",
            r"require\s*\(['\"]path['\"]\)",
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, code):
                return False, f"Dangerous pattern detected: {pattern}"
    
    return True, None


# =============================================================================
# User Input Validation
# =============================================================================

def validate_user_input(
    input_str: str,
    max_length: int = 1000,
    allow_unicode: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Validate general user input.
    
    Args:
        input_str: The input string to validate.
        max_length: Maximum allowed length.
        allow_unicode: Whether to allow Unicode characters.
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    if not input_str:
        return True, None  # Empty is OK for optional fields
    
    # Check length
    if len(input_str) > max_length:
        return False, f"Input too long (max {max_length} characters)"
    
    # Check character set
    if allow_unicode:
        # Just check for control characters
        if any(ord(c) < 32 and c not in "\t\n\r" for c in input_str):
            return False, "Control characters not allowed"
    else:
        # ASCII only
        try:
            input_str.encode('ascii')
        except UnicodeEncodeError:
            return False, "Only ASCII characters allowed"
    
    return True, None


def validate_identifier(identifier: str, identifier_type: str = "ID") -> Tuple[bool, Optional[str]]:
    """
    Validate an identifier (user ID, sandbox ID, etc.).
    
    Args:
        identifier: The identifier to validate.
        identifier_type: Human-readable type name for error messages.
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    if not identifier:
        return False, f"{identifier_type} cannot be empty"
    
    # Check format: alphanumeric, underscore, hyphen
    if not re.match(r'^[a-zA-Z0-9_-]+$', identifier):
        return False, f"Invalid {identifier_type} format. Only alphanumeric, underscore, and hyphen allowed"
    
    # Check length
    if len(identifier) > 256:
        return False, f"{identifier_type} too long (max 256 characters)"
    
    # Check for path traversal
    if ".." in identifier:
        return False, f"{identifier_type} cannot contain '..'"
    
    return True, None


# =============================================================================
# URL and Network Validation
# =============================================================================

def validate_url(url: str, allowed_schemes: Optional[List[str]] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate a URL.
    
    Args:
        url: The URL to validate.
        allowed_schemes: List of allowed URL schemes (e.g., ["http", "https"]).
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    if not url:
        return False, "URL cannot be empty"
    
    # Basic URL pattern
    url_pattern = re.compile(
        r'^'
        r'(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*)://'
        r'(?:(?P<user>[a-zA-Z0-9._~%+-]+)'
        r'(?::(?P<password>[^@]+))?@)?'
        r'(?P<host>[a-zA-Z0-9._~%-]+(?:\.[a-zA-Z0-9._~%-]+)*'
        r'|(?:\[(?:[0-9a-fA-F:]+)\]))'
        r'(?::(?P<port>\d+))?'
        r'(?:/(?P<path>[^\s?#]*))?'
        r'(?:\?(?P<query>[^\s#]*))?'
        r'(?:\#(?P<fragment>[^\s]*))?'
        r'$'
    )
    
    match = url_pattern.match(url)
    if not match:
        return False, "Invalid URL format"
    
    # Check scheme
    scheme = match.group('scheme').lower()
    if allowed_schemes:
        if scheme not in [s.lower() for s in allowed_schemes]:
            return False, f"URL scheme not allowed. Allowed: {', '.join(allowed_schemes)}"
    
    # Check for internal/private IPs
    host = match.group('host') or ""
    if host in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
        return False, "Internal addresses not allowed"
    
    # Check for private IP ranges
    private_patterns = [
        r'^10\.',
        r'^172\.(1[6-9]|2[0-9]|3[0-1])\.',
        r'^192\.168\.',
        r'^169\.254\.',
    ]
    for pattern in private_patterns:
        if re.match(pattern, host):
            return False, "Private IP addresses not allowed"
    
    return True, None


# =============================================================================
# Request Payload Validation
# =============================================================================

def validate_sandbox_create_payload(payload: dict) -> Tuple[bool, Optional[str]]:
    """
    Validate a sandbox creation request payload.
    
    Args:
        payload: The request payload dictionary.
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    # Check sandbox_id if provided
    if "sandbox_id" in payload and payload["sandbox_id"] is not None:
        is_valid, error = validate_identifier(payload["sandbox_id"], "Sandbox ID")
        if not is_valid:
            return False, error
    
    # Check for unexpected fields
    allowed_fields = {"sandbox_id"}
    extra_fields = set(payload.keys()) - allowed_fields
    if extra_fields:
        return False, f"Unexpected fields: {', '.join(extra_fields)}"
    
    return True, None


def validate_exec_payload(payload: dict) -> Tuple[bool, Optional[str]]:
    """
    Validate a command execution request payload.
    
    Args:
        payload: The request payload dictionary.
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    # Check command
    if "command" not in payload:
        return False, "Command is required"
    
    is_valid, error = validate_command(payload["command"])
    if not is_valid:
        return False, error
    
    # Check args if provided
    if "args" in payload and payload["args"]:
        if not isinstance(payload["args"], list):
            return False, "Args must be a list"
        
        for arg in payload["args"]:
            is_valid, error = validate_command_arg(arg)
            if not is_valid:
                return False, error
    
    # Check code if provided
    if "code" in payload and payload["code"]:
        is_valid, error = validate_code_input(payload["code"])
        if not is_valid:
            return False, error
    
    # Check timeout if provided
    if "timeout" in payload and payload["timeout"] is not None:
        if not isinstance(payload["timeout"], int):
            return False, "Timeout must be an integer"
        if payload["timeout"] < 1 or payload["timeout"] > 300:
            return False, "Timeout must be between 1 and 300 seconds"
    
    return True, None


# =============================================================================
# Convenience Functions
# =============================================================================

def validate_all(*validations: Tuple[bool, Optional[str]]) -> Tuple[bool, Optional[str]]:
    """
    Validate multiple checks and return the first failure.
    
    Args:
        *validations: List of (is_valid, error_message) tuples.
        
    Returns:
        Tuple of (all_valid, first_error_message).
    """
    for is_valid, error in validations:
        if not is_valid:
            return False, error
    return True, None
