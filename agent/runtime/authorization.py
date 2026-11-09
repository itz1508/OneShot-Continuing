"""Compatibility API: one implementation lives in system.host.authorization."""

from system.host.authorization import (
    AuthorizationError as AuthorizationError,
    Capability as Capability,
    PermissionGrant as PermissionGrant,
    EmptyGrant as EmptyGrant,
    AuthorizationEngine as AuthorizationEngine,
    RolePolicy as RolePolicy,
    PathAuthorizer as PathAuthorizer,
)
