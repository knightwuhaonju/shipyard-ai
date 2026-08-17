"""Authentication adapter implementations."""

from adapters.auth.local import AuthenticationError, LocalAuthenticationAdapter

__all__ = ["AuthenticationError", "LocalAuthenticationAdapter"]
