# Identity Provider Configuration

## DO NOT Build Auth From Scratch

Never roll your own:
- Password storage
- OAuth flows
- MFA

Instead, delegate identity and keep only the user ID.

## Recommended Identity Providers

### External Identity Provider (IdP) Options

Use one of:

1. **Auth0**
   - Enterprise-grade authentication
   - Wide OAuth provider support
   - Built-in MFA

2. **Clerk**
   - Developer-friendly
   - Modern UI components
   - Easy integration

3. **Supabase Auth**
   - Open source
   - PostgreSQL-backed
   - Self-hostable

4. **Keycloak**
   - Self-hosted solution
   - Full control
   - SAML and OAuth support

## What They Handle

Identity providers handle:
- Login flows
- OAuth (GitHub / Google / etc.)
- JWT token generation
- MFA (Multi-factor authentication)
- Password reset
- Session management

## What You Handle

You only handle:
- Mapping JWT → user_id
- Storing user_id in your database
- Associating user_id with workspaces/containers

## Integration Example

```python
import re
from jose import jwt

def validate_user_id(user_id: str) -> bool:
    """
    Validate user ID to prevent path traversal and command injection
    """
    # Allow alphanumeric characters, hyphens, underscores, and pipe (for IdP formats like auth0|...)
    return bool(re.match(r'^(?!.*\.\.)[a-zA-Z0-9_\-\|:.@]+$', user_id))

def get_user_id(token: str):
    payload = jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
    user_id = payload["sub"]   # stable user id

    # Validate user_id to prevent path traversal
    if not validate_user_id(user_id):
        raise ValueError("Invalid user ID format")

    return user_id
```

The `sub` claim becomes your stable user identifier (e.g., `u_auth0_abc123`).

## Security Best Practices

✔ Never store passwords yourself
✔ Always validate JWT signatures
✔ Use HTTPS for all authentication endpoints
✔ Rotate signing keys periodically
✔ Implement token expiration and refresh
✔ Log authentication events
✔ Rate limit authentication endpoints

## Mapping Identity to Resources

```python
user_id = get_user_id(token)

workspace = f"/srv/workspaces/{user_id}"
container = f"shell-{user_id}"
```

This mapping never changes and provides stable resource allocation per user.
