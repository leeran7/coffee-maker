"""codex-sub: ChatGPT-subscription GPT access without an API key.

Uses the same OAuth tokens as `codex login` (device flow) and calls the
subscription-backed Responses endpoint. Usage draws from the ChatGPT plan's
allowance — no Platform billing, no static API key to manage.

Fragility warning: this rides the Codex CLI's undocumented auth surface.
OpenAI can change endpoints, token shapes, or model allowlists at any time.
"""

from .auth import AuthError, account_id, ensure_fresh_tokens, refresh_now, token_expiry
from .client import ClientError, DEFAULT_MODEL, complete

__all__ = [
    "AuthError",
    "ClientError",
    "DEFAULT_MODEL",
    "account_id",
    "complete",
    "ensure_fresh_tokens",
    "refresh_now",
    "token_expiry",
]
