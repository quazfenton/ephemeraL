"""
Identity and Authentication Module
Handles JWT-based authentication and user identity management

Security Features:
- JWT token validation with RS256 algorithm
- Audience and issuer validation (fail-closed in production)
- User ID validation to prevent path traversal and command injection
- Runtime configuration validation
- Comprehensive error logging with security context

Environment Variables:
- JWT_PUBLIC_KEY: RSA public key for JWT verification (PEM format)
- JWT_AUDIENCE: Expected JWT audience claim (required in production)
- JWT_ISSUER: Expected JWT issuer claim (optional but recommended)
- ENVIRONMENT: Deployment environment (development|staging|production)
- WORKSPACE_BASE_DIR: Base directory for user workspaces
- CONTAINER_PREFIX: Prefix for container names
"""

import os
import re
import logging
from typing import Optional, Tuple
from jose import jwt, ExpiredSignatureError, JWTError

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Get environment setting (defaults to development for backward compatibility)
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Configuration validation flag
_config_validated = False


def _validate_configuration() -> None:
    """
    Validate authentication configuration at runtime.

    Raises:
        RuntimeError: If required configuration is missing in production.
    """
    global _config_validated

    if _config_validated:
        return

    # Check public key
    if "YOUR_PUBLIC_KEY_HERE" in PUBLIC_KEY or not PUBLIC_KEY.strip():
        if ENVIRONMENT == "production":
            raise RuntimeError(
                "JWT PUBLIC_KEY not configured. In production, a valid RSA public key is required. "
                "Set JWT_PUBLIC_KEY environment variable or update PUBLIC_KEY in auth.py. "
                "For development only, set ENVIRONMENT=development."
            )
        else:
            logger.warning(
                "⚠️  WARNING: Using placeholder PUBLIC_KEY. Authentication will fail. "
                "Set JWT_PUBLIC_KEY environment variable. "
                "This warning is expected in development but CRITICAL in production."
            )

    # Check audience configuration
    if not os.getenv("JWT_AUDIENCE"):
        if ENVIRONMENT == "production":
            raise RuntimeError(
                "JWT_AUDIENCE not configured. In production, audience validation is required for security. "
                "Set JWT_AUDIENCE environment variable to your API identifier. "
                "For development only, set ENVIRONMENT=development."
            )
        else:
            logger.warning(
                "⚠️  WARNING: JWT_AUDIENCE not set - audience validation disabled. "
                "This allows tokens from any audience. CRITICAL for production. "
                "Set JWT_AUDIENCE or ENVIRONMENT=production to enforce."
            )

    # Check issuer configuration (recommended but not required)
    if not os.getenv("JWT_ISSUER"):
        if ENVIRONMENT == "production":
            logger.warning(
                "⚠️  WARNING: JWT_ISSUER not set in production. "
                "Issuer validation is recommended for defense-in-depth."
            )

    _config_validated = True


# =============================================================================
# User ID Validation
# =============================================================================

# Compiled regex for performance (validates format in one pass)
_USER_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


def validate_user_id(user_id: str) -> bool:
    """
    Validate user ID to prevent path traversal and command injection.

    Security Rules:
    - Only ASCII alphanumeric characters allowed
    - Hyphens and underscores permitted for readability
    - No path separators (/, \\) to prevent directory traversal
    - No shell metacharacters to prevent command injection
    - Maximum length enforced (256 characters)

    Args:
        user_id: User ID string to validate

    Returns:
        True if valid, False otherwise

    Examples:
        >>> validate_user_id("auth0|user123")
        False  # Pipe character not allowed
        >>> validate_user_id("user_abc-123")
        True   # Valid format
        >>> validate_user_id("../etc/passwd")
        False  # Path traversal attempt
    """
    if not user_id:
        return False

    # Check maximum length (prevent DoS via long strings)
    if len(user_id) > 256:
        return False

    # Validate format using compiled regex (single pass)
    if not _USER_ID_PATTERN.match(user_id):
        return False

    # Defense in depth: ensure all characters are ASCII
    # (regex already ensures this, but explicit check for clarity)
    try:
        user_id.encode('ascii')
    except UnicodeEncodeError:
        return False

    return True


def validate_user_id_strict(user_id: str) -> Tuple[bool, Optional[str]]:
    """
    Validate user ID and return specific error message.

    Like validate_user_id() but provides detailed error messages
    for debugging and user feedback.

    Args:
        user_id: User ID string to validate

    Returns:
        Tuple of (is_valid, error_message)
        If valid, error_message is None.

    Examples:
        >>> validate_user_id_strict("")
        (False, "User ID cannot be empty")
        >>> validate_user_id_strict("a" * 300)
        (False, "User ID too long (max 256 characters)")
    """
    if not user_id:
        return False, "User ID cannot be empty"

    if len(user_id) > 256:
        return False, f"User ID too long (max 256 characters, got {len(user_id)})"

    if not _USER_ID_PATTERN.match(user_id):
        # Identify specific issue for better error message
        if '/' in user_id or '\\' in user_id:
            return False, "User ID cannot contain path separators"
        if any(c in user_id for c in ';|&$`!'):
            return False, "User ID cannot contain shell metacharacters"
        return False, "User ID must contain only alphanumeric characters, hyphens, and underscores"

    try:
        user_id.encode('ascii')
    except UnicodeEncodeError:
        return False, "User ID must contain only ASCII characters"

    return True, None


# =============================================================================
# JWT Token Processing
# =============================================================================

def get_user_id(token: str) -> str:
    """
    Extract and validate user ID from JWT token.

    Security Features:
    - RS256 algorithm enforcement (prevents algorithm confusion attacks)
    - Audience validation (fail-closed in production)
    - Issuer validation (when configured)
    - Expiration checking (automatic via jose library)
    - User ID format validation (prevents injection)
    - Detailed error messages for debugging (without leaking secrets)

    Args:
        token: JWT token string from Authorization header

    Returns:
        Stable user ID (sub claim from JWT)

    Raises:
        ValueError: If token is invalid, expired, or missing required claims.
        RuntimeError: If configuration is invalid in production.

    Security Notes:
        - In production (ENVIRONMENT=production), missing JWT_AUDIENCE raises error
        - In development, missing configuration only logs warnings
        - All validation failures are logged for security monitoring
        - Error messages are specific enough for debugging but don't leak sensitive info
    """
    # Validate configuration before processing token
    _validate_configuration()

    try:
        # Build decode kwargs with security defaults
        decode_kwargs = {
            "algorithms": ["RS256"],  # Enforce RS256 only (prevents algorithm confusion)
            "options": {
                "verify_signature": True,
                "verify_exp": True,  # Verify expiration (default, but explicit for clarity)
                "verify_nbf": True,  # Verify not-before claim
                "verify_iat": True,  # Verify issued-at claim
                "require": ["exp"],  # Expiration is mandatory
            }
        }

        # Add audience validation (critical for security)
        audience = os.getenv("JWT_AUDIENCE")
        if audience:
            decode_kwargs["audience"] = audience
        elif ENVIRONMENT != "production":
            # Development mode: warn but continue
            logger.debug("JWT audience validation disabled (development mode)")

        # Add issuer validation (defense in depth)
        issuer = os.getenv("JWT_ISSUER")
        if issuer:
            decode_kwargs["issuer"] = issuer

        # Decode and validate token
        payload = jwt.decode(token, PUBLIC_KEY, **decode_kwargs)

    except ExpiredSignatureError:
        logger.info("JWT token expired", extra={"auth_event": "token_expired"})
        raise ValueError("Token has expired") from None

    except JWTError as e:
        # Log specific error for debugging, return generic message to user
        error_type = type(e).__name__
        logger.info(
            f"JWT validation failed: {error_type}",
            extra={
                "auth_event": "token_invalid",
                "error_type": error_type,
            }
        )
        raise ValueError(f"Invalid token: {error_type}") from None

    except Exception as e:
        # Unexpected error - log full details, return generic message
        logger.exception(f"Unexpected token decode error: {e}")
        raise ValueError("Token decode failed") from None

    # Validate required claims
    if "sub" not in payload:
        available_claims = list(payload.keys()) if payload else []
        logger.error(
            f"Token missing 'sub' claim. Available claims: {available_claims}",
            extra={"auth_event": "missing_sub_claim"}
        )
        raise ValueError(
            f"Token missing 'sub' claim. Available claims: {available_claims}. "
            f"Check your identity provider configuration."
        )

    # Extract and validate user ID
    user_id = payload["sub"]  # sub = subject = stable user identifier

    # Validate user_id format to prevent injection attacks
    is_valid, error = validate_user_id_strict(user_id)
    if not is_valid:
        logger.warning(
            f"Invalid user ID format in token: {error}",
            extra={
                "auth_event": "invalid_user_id",
                "user_id_prefix": user_id[:8] if user_id else None,  # Log prefix for debugging
            }
        )
        raise ValueError(f"Invalid user ID format: {error}")

    return user_id


# =============================================================================
# Workspace Mapping
# =============================================================================

def map_user_to_workspace(token: str) -> Tuple[str, str]:
    """
    Map authenticated user to their workspace path and container name.

    This function enforces the "one user → one workspace" security model.
    The mapping is deterministic and based solely on the user's stable ID.

    Args:
        token: JWT token string

    Returns:
        Tuple of (workspace_path, container_name)

    Security Notes:
        - Workspace paths are namespaced by user_id (no cross-user access)
        - Container names are derived from user_id (predictable but isolated)
        - Paths use configurable base directory for deployment flexibility

    Environment Variables:
        WORKSPACE_BASE_DIR: Base directory for workspaces (default: /srv/workspaces)
        CONTAINER_PREFIX: Prefix for container names (default: shell-)
    """
    # Authenticate user first
    user_id = get_user_id(token)

    # Get configuration with secure defaults
    workspace_base_dir = os.getenv("WORKSPACE_BASE_DIR", "/srv/workspaces")
    container_prefix = os.getenv("CONTAINER_PREFIX", "shell-")

    # Validate workspace base directory (prevent path injection)
    if not workspace_base_dir.startswith('/'):
        logger.error(
            f"WORKSPACE_BASE_DIR must be absolute path: {workspace_base_dir}",
            extra={"config_event": "invalid_workspace_base"}
        )
        if ENVIRONMENT == "production":
            raise RuntimeError("WORKSPACE_BASE_DIR must be an absolute path")
        # In development, use safe default
        workspace_base_dir = "/srv/workspaces"

    # Construct workspace path and container name
    workspace_path = f"{workspace_base_dir.rstrip('/')}/{user_id}"
    container_name = f"{container_prefix}{user_id}"

    logger.debug(
        f"Mapped user {user_id[:8]}... to workspace {workspace_path}",
        extra={"auth_event": "workspace_mapped"}
    )

    return workspace_path, container_name


# =============================================================================
# Public Key Configuration
# =============================================================================

# Default placeholder - MUST be replaced with actual public key
# Format: PEM-encoded RSA public key
PUBLIC_KEY = os.getenv(
    "JWT_PUBLIC_KEY",
    """
-----BEGIN PUBLIC KEY-----
YOUR_PUBLIC_KEY_HERE
-----END PUBLIC KEY-----
"""
)

# =============================================================================
# Security Rules Documentation
# =============================================================================

# Identity Security Rules:
# ✔ One user → one workspace (enforced by deterministic mapping)
# ✔ Tokens required for all APIs (validated at API gateway)
# ✔ Containers never see auth tokens (tokens stripped before exec)
# ✔ LLM never sees identity secrets (secrets in env vars only)
# ✔ Fail-closed in production (missing config = error, not warning)
# ✔ Comprehensive audit logging (all auth events logged)

# =============================================================================
# Module Initialization
# =============================================================================

def initialize_module() -> None:
    """
    Initialize authentication module with runtime validation.

    Call this at application startup to ensure configuration is valid
    before accepting any requests.

    Raises:
        RuntimeError: If required configuration is missing in production.
    """
    _validate_configuration()
    logger.info(
        f"Authentication module initialized (environment={ENVIRONMENT})",
        extra={
            "module": "auth",
            "environment": ENVIRONMENT,
            "audience_configured": bool(os.getenv("JWT_AUDIENCE")),
            "issuer_configured": bool(os.getenv("JWT_ISSUER")),
        }
    )


# Auto-initialize on import (can be disabled for testing)
if os.getenv("AUTH_AUTO_INIT", "true").lower() == "true":
    try:
        initialize_module()
    except RuntimeError:
        # Re-raise in production, log and continue in development
        if ENVIRONMENT == "production":
            raise
        logger.warning("Module initialization failed (development mode)")
