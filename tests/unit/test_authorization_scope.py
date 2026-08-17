from typing import Any, cast

import pytest
from pydantic import ValidationError


def test_authorization_scope_defaults_to_deny_all_scoped_dimensions() -> None:
    from packages.contracts.auth import AuthorizationScope, SecurityLevel

    scope = AuthorizationScope()

    assert scope.roles == frozenset()
    assert scope.departments == frozenset()
    assert scope.allowed_ship_ids == frozenset()
    assert scope.allowed_project_ids == frozenset()
    assert scope.security_level is SecurityLevel.PUBLIC


def test_scope_intersection_narrows_every_dimension_and_clearance() -> None:
    from packages.contracts.auth import AuthorizationScope, SecurityLevel

    authenticated = AuthorizationScope(
        roles={"project_manager", "engineer"},
        departments={"design", "production"},
        allowed_ship_ids={"ship-001", "ship-002"},
        allowed_project_ids={"project-001", "project-002"},
        security_level=SecurityLevel.CONFIDENTIAL,
    )
    requested = AuthorizationScope(
        roles={"project_manager", "procurement"},
        departments={"production", "quality"},
        allowed_ship_ids={"ship-002", "ship-003"},
        allowed_project_ids={"project-002", "project-003"},
        security_level=SecurityLevel.RESTRICTED,
    )

    result = authenticated.intersection(requested)

    assert result == AuthorizationScope(
        roles={"project_manager"},
        departments={"production"},
        allowed_ship_ids={"ship-002"},
        allowed_project_ids={"project-002"},
        security_level=SecurityLevel.CONFIDENTIAL,
    )


def test_disjoint_scope_intersection_stays_empty() -> None:
    from packages.contracts.auth import AuthorizationScope, SecurityLevel

    result = AuthorizationScope(
        roles={"engineering"},
        departments={"design"},
        allowed_ship_ids={"ship-001"},
        allowed_project_ids={"project-001"},
        security_level=SecurityLevel.INTERNAL,
    ).intersection(
        AuthorizationScope(
            roles={"procurement"},
            departments={"supply"},
            allowed_ship_ids={"ship-002"},
            allowed_project_ids={"project-002"},
            security_level=SecurityLevel.PUBLIC,
        )
    )

    assert result == AuthorizationScope(security_level=SecurityLevel.PUBLIC)


def test_auth_contracts_are_immutable_and_reject_unknown_fields() -> None:
    from packages.contracts.auth import AuthorizationScope, SecurityLevel, UserContext

    scope = AuthorizationScope(roles={"engineering"})
    context = UserContext(user_id="user-001", roles={"engineering"})

    assert isinstance(scope.roles, frozenset)
    assert isinstance(context.roles, frozenset)
    with pytest.raises(ValidationError):
        cast(Any, scope).security_level = SecurityLevel.RESTRICTED
    with pytest.raises(ValidationError):
        cast(Any, context).user_id = "attacker"
    with pytest.raises(ValidationError):
        AuthorizationScope.model_validate(
            {"roles": ["engineering"], "user_id": "attacker"}
        )
    with pytest.raises(ValidationError):
        UserContext.model_validate(
            {"user_id": "user-001", "model_supplied_role": "admin"}
        )
