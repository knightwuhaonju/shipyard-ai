"""Development-only authentication backed by a server-owned registry."""

from collections.abc import Mapping

from packages.contracts.auth import UserContext


class AuthenticationError(RuntimeError):
    """Raised when a local credential cannot be authenticated."""


class LocalAuthenticationAdapter:
    """Resolve opaque local credentials without accepting identity claims."""

    def __init__(self, identities: Mapping[str, UserContext]) -> None:
        self._identities = dict(identities)

    def authenticate(self, credential: str | None) -> UserContext:
        if not isinstance(credential, str) or not credential:
            raise AuthenticationError("Authentication failed")
        context = self._identities.get(credential)
        if context is None:
            raise AuthenticationError("Authentication failed")
        return context
