"""Compatibility API: one implementation lives in system.host.authorization."""

from system.host.authorization import (
    AuthorizationEngine as AuthorizationEngine,
    AuthorizationError as AuthorizationError,
    Capability as Capability,
    EmptyGrant as EmptyGrant,
    PathAuthorizer as PathAuthorizer,
    PermissionGrant as PermissionGrant,
    RolePolicy as RolePolicy,
)
