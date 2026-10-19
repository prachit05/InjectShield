"""Verify Cognito JWTs. Signing keys come from the pool's JWKS and are cached.

Accepts both ID tokens (audience = app client id) and access tokens
(client_id claim = app client id). With AUTH_DISABLED=true every request runs
as DEV_USER_ID; that flag is for local development only.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from injectshield_shared.config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


class CognitoVerifier:
    def __init__(self, issuer: str, client_id: str, key_resolver: Callable[[str], object] | None = None):
        self.issuer = issuer
        self.client_id = client_id
        if key_resolver is None:
            jwks = jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600)
            key_resolver = lambda token: jwks.get_signing_key_from_jwt(token).key  # noqa: E731
        self._key_for = key_resolver

    def verify(self, token: str) -> dict:
        claims = jwt.decode(
            token,
            self._key_for(token),
            algorithms=["RS256"],
            issuer=self.issuer,
            options={"verify_aud": False, "require": ["exp", "iat", "iss", "sub", "token_use"]},
        )
        token_use = claims["token_use"]
        if token_use == "id":  # noqa: S105 (claim value, not a secret)
            audience_ok = claims.get("aud") == self.client_id
        elif token_use == "access":  # noqa: S105
            audience_ok = claims.get("client_id") == self.client_id
        else:
            audience_ok = False
        if not audience_ok:
            raise jwt.InvalidTokenError("token was not issued for this app client")
        return claims


@lru_cache
def _verifier(issuer: str, client_id: str) -> CognitoVerifier:
    return CognitoVerifier(issuer, client_id)


def get_verifier(settings: Annotated[Settings, Depends(get_settings)]) -> CognitoVerifier | None:
    if settings.auth_disabled:
        return None
    return _verifier(settings.cognito_issuer, settings.cognito_app_client_id)


def current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    verifier: Annotated[CognitoVerifier | None, Depends(get_verifier)],
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    """Returns the caller's Cognito sub."""
    if settings.auth_disabled:
        return settings.dev_user_id
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing or invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None or verifier is None:
        raise unauthorized
    try:
        claims = verifier.verify(creds.credentials)
    except jwt.PyJWTError as exc:
        raise unauthorized from exc
    return claims["sub"]
