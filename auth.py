"""
Identity and Authentication Module
Handles JWT-based authentication and user identity management
"""

from jose import jwt


def get_user_id(token: str) -> str:
    """
    Extract user ID from JWT token
    
    Args:
        token: JWT token string
        
    Returns:
        Stable user ID (sub claim from JWT)
    """
    payload = jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
    return payload["sub"]  # stable user id


def map_user_to_workspace(token: str) -> tuple[str, str]:
    """
    Map authenticated user to their workspace and container
    
    Args:
        token: JWT token string
        
    Returns:
        Tuple of (workspace_path, container_name)
    """
    user_id = get_user_id(token)
    
    if not user_id or not all(c.isalnum() or c in '-_' for c in user_id):
        raise ValueError("Invalid user_id format")
    workspace = f"/srv/workspaces/{user_id}"
    container = f"shell-{user_id}"
    
    return workspace, container


# Configuration - Replace with your actual public key
PUBLIC_KEY = """
-----BEGIN PUBLIC KEY-----
YOUR_PUBLIC_KEY_HERE
-----END PUBLIC KEY-----
"""

# Identity Security Rules:
# ✔ One user → one workspace
# ✔ Tokens required for all APIs
# ✔ Containers never see auth tokens
# ✔ LLM never sees identity secrets
