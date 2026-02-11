"""
Identity and Authentication Module
Handles JWT-based authentication and user identity management
"""

import os
import re
import warnings
from jose import jwt, ExpiredSignatureError, JWTError


def validate_user_id(user_id: str) -> bool:
    """
    Validate user ID to prevent path traversal and command injection

    Args:
        user_id: User ID string to validate

    Returns:
        True if valid, False otherwise
    """
    # Allow only ASCII alphanumeric characters, hyphens, and underscores
    # Check that the string matches the pattern AND contains only ASCII characters
    if not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
        return False

    # Ensure all characters are ASCII (important for Docker container names)
    return all(ord(c) < 128 for c in user_id)


def get_user_id(token: str) -> str:
    """
    Extract user ID from JWT token

    Args:
        token: JWT token string

    Returns:
        Stable user ID (sub claim from JWT)
    """
    try:
        decode_kwargs = {"algorithms": ["RS256"]}
        audience = os.getenv("JWT_AUDIENCE")
        issuer = os.getenv("JWT_ISSUER")
        decode_kwargs = {"algorithms": ["RS256"]}
        audience = os.getenv("JWT_AUDIENCE")
        issuer = os.getenv("JWT_ISSUER")
        if audience:
            decode_kwargs["audience"] = audience
        else:
            import warnings
            warnings.warn("JWT_AUDIENCE not set — audience validation disabled", RuntimeWarning, stacklevel=2)
        if issuer:
            decode_kwargs["issuer"] = issuer
        payload = jwt.decode(token, PUBLIC_KEY, **decode_kwargs)
    except ExpiredSignatureError:
        raise ValueError("Token has expired")
    except JWTError as e:
        raise ValueError(f"Invalid token: {str(e)}")
    except Exception as e:
        raise ValueError(f"Token decode failed: {str(e)}")

    if "sub" not in payload:
        raise ValueError("Token missing 'sub' claim")

    user_id = payload["sub"]  # stable user id

    # Validate user_id to prevent path traversal
    if not validate_user_id(user_id):
        raise ValueError("Invalid user ID format")

    return user_id


def map_user_to_workspace(token: str) -> tuple[str, str]:
    """
    Map authenticated user to their workspace and container

    Args:
        token: JWT token string

    Returns:
        Tuple of (workspace_path, container_name)
    """
    user_id = get_user_id(token)

    workspace = f"/srv/workspaces/{user_id}"
    container = f"shell-{user_id}"

    return workspace, container


# Configuration - Replace with your actual public key
PUBLIC_KEY = """
-----BEGIN PUBLIC KEY-----
YOUR_PUBLIC_KEY_HERE
-----END PUBLIC KEY-----
"""

# Startup validation to detect placeholder key
if "YOUR_PUBLIC_KEY_HERE" in PUBLIC_KEY:
    warnings.warn(
        "WARNING: Using placeholder PUBLIC_KEY - please configure with actual key",
        RuntimeWarning,
        stacklevel=2
    )

# Identity Security Rules:
# ✔ One user → one workspace
# ✔ Tokens required for all APIs
# ✔ Containers never see auth tokens
# ✔ LLM never sees identity secrets
