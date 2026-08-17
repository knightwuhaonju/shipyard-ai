"""Server-side authorization scope derivation."""

from packages.contracts.auth import AuthorizationScope, UserContext


def authorization_scope_for(
    user_context: UserContext,
    requested_scope: AuthorizationScope | None = None,
) -> AuthorizationScope:
    """Derive trusted permissions and optionally narrow them."""
    authenticated_scope = AuthorizationScope(
        roles=user_context.roles,
        departments=user_context.departments,
        allowed_ship_ids=user_context.allowed_ship_ids,
        allowed_project_ids=user_context.allowed_project_ids,
        security_level=user_context.security_clearance,
    )
    if requested_scope is None:
        return authenticated_scope
    return authenticated_scope.intersection(requested_scope)
