"""Supabase Auth integration: verify the access token the mobile app sends as a bearer token.

Supabase projects sign access tokens either with a shared HS256 secret (legacy) or with
asymmetric signing keys published at `<project>/auth/v1/.well-known/jwks.json`. Both work here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.types import Options
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from brian.config import Settings, get_settings
from brian.db import get_session
from brian.models import Profile


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str | None


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._audience = settings.supabase_jwt_audience
        self._secret = settings.supabase_jwt_secret.get_secret_value() if settings.supabase_jwt_secret else None
        self._jwks: jwt.PyJWKClient | None = None
        if self._secret is None:
            self._jwks = jwt.PyJWKClient(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
                cache_jwk_set=True,
                lifespan=600,
            )

    def verify(self, token: str) -> dict[str, Any]:
        """Return the token's claims, or raise `jwt.PyJWTError`. Blocking when JWKS must be fetched."""
        options: Options = {"require": ["exp", "sub"]}
        if self._secret is not None:
            return jwt.decode(token, self._secret, algorithms=["HS256"], audience=self._audience, options=options)
        assert self._jwks is not None
        signing_key = self._jwks.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256", "EdDSA"],
            audience=self._audience,
            options=options,
        )


@lru_cache
def get_token_verifier() -> TokenVerifier:
    return TokenVerifier(get_settings())


_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> CurrentUser:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        claims = await run_in_threadpool(verifier.verify, credentials.credentials)
        user_id = uuid.UUID(str(claims["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise unauthorized from exc
    return CurrentUser(id=user_id, email=claims.get("email"))


async def get_profile(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Profile:
    """The caller's profile. Created on first use if the sign-up trigger has not made it yet."""
    profile = await session.get(Profile, user.id)
    if profile is None:
        await session.execute(insert(Profile).values(id=user.id).on_conflict_do_nothing())
        await session.commit()
        profile = await session.get(Profile, user.id)
        if profile is None:  # pragma: no cover - only if the auth user vanished mid-request
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return profile


CurrentProfile = Annotated[Profile, Depends(get_profile)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
