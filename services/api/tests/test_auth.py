"""Token verification for both Supabase signing setups: the shared HS256 secret (local `supabase
start`, legacy projects) and asymmetric signing keys published as JWKS (current hosted projects)."""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from brian.auth import TokenVerifier
from brian.config import get_settings
from tests.conftest import JWT_SECRET, make_token


class FakeJwks:
    """Stands in for the project's /auth/v1/.well-known/jwks.json."""

    def __init__(self, public_jwk: dict[str, Any]) -> None:
        self.jwk = public_jwk

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        assert jwt.get_unverified_header(token)["kid"] == self.jwk["kid"]
        return jwt.PyJWK(self.jwk)


def es256_token(key: ec.EllipticCurvePrivateKey, sub: uuid.UUID, kid: str = "key-1") -> str:
    now = int(time.time())
    claims = {"sub": str(sub), "aud": "authenticated", "role": "authenticated", "iat": now, "exp": now + 600}
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})


@pytest.fixture
def signing_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def verifier_with_jwks(signing_key: ec.EllipticCurvePrivateKey, *, secret: str | None) -> TokenVerifier:
    settings = get_settings().model_copy(update={"supabase_jwt_secret": None})
    if secret is not None:
        settings = get_settings()
    verifier = TokenVerifier(settings)
    public_jwk = ECAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    verifier._jwks = FakeJwks({**public_jwk, "kid": "key-1", "alg": "ES256", "use": "sig"})  # type: ignore[assignment]
    return verifier


def test_hs256_tokens_use_the_shared_secret(signing_key: ec.EllipticCurvePrivateKey) -> None:
    user = uuid.uuid4()
    claims = verifier_with_jwks(signing_key, secret=JWT_SECRET).verify(make_token(user))
    assert claims["sub"] == str(user)


def test_asymmetric_tokens_use_the_published_keys(signing_key: ec.EllipticCurvePrivateKey) -> None:
    user = uuid.uuid4()
    for secret in (JWT_SECRET, None):  # works with or without a shared secret configured
        claims = verifier_with_jwks(signing_key, secret=secret).verify(es256_token(signing_key, user))
        assert claims["sub"] == str(user)


def test_forged_and_confused_tokens_are_rejected(signing_key: ec.EllipticCurvePrivateKey) -> None:
    verifier = verifier_with_jwks(signing_key, secret=JWT_SECRET)
    other_key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(jwt.InvalidSignatureError):
        verifier.verify(es256_token(other_key, uuid.uuid4()))
    unsigned = jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": "authenticated", "exp": int(time.time()) + 60}, None, "none"
    )
    with pytest.raises(jwt.InvalidAlgorithmError):
        verifier.verify(unsigned)
    without_secret = verifier_with_jwks(signing_key, secret=None)
    with pytest.raises(jwt.InvalidTokenError):
        without_secret.verify(make_token(uuid.uuid4()))
