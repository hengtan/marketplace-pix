from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

logger = logging.getLogger(__name__)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def public_jwk(public_key: Ed25519PublicKey) -> dict[str, str]:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": _b64url(raw)}
    thumbprint = hashlib.sha256(
        json.dumps(jwk, sort_keys=True, separators=(",", ":")).encode()
    ).digest()
    return {**jwk, "kid": _b64url(thumbprint), "use": "sig", "alg": "EdDSA"}


@dataclass(frozen=True, slots=True)
class SigningKeys:
    private_key: Ed25519PrivateKey
    retired_public_keys: tuple[Ed25519PublicKey, ...] = ()

    @property
    def kid(self) -> str:
        return public_jwk(self.private_key.public_key())["kid"]

    def jwks(self) -> dict[str, Any]:
        keys = [public_jwk(self.private_key.public_key())]
        keys.extend(public_jwk(k) for k in self.retired_public_keys)
        return {"keys": keys}


def generate_private_pem() -> str:
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _normalize_pem(value: str) -> bytes:
    return value.replace("\\n", "\n").strip().encode()


def load_signing_keys(
    private_pem: str, retired_public_pems: list[str], allow_ephemeral: bool
) -> SigningKeys:
    if not private_pem:
        if not allow_ephemeral:
            raise RuntimeError("IDENTITY_SIGNING_KEY is required outside development")
        private_key = Ed25519PrivateKey.generate()
        logger.warning("using an ephemeral signing key: tokens will not survive a restart")
    else:
        loaded = serialization.load_pem_private_key(_normalize_pem(private_pem), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise RuntimeError("IDENTITY_SIGNING_KEY must be an Ed25519 private key")
        private_key = loaded
    retired: list[Ed25519PublicKey] = []
    for pem in retired_public_pems:
        public = serialization.load_pem_public_key(_normalize_pem(pem))
        if not isinstance(public, Ed25519PublicKey):
            raise RuntimeError("retired keys must be Ed25519 public keys")
        retired.append(public)
    return SigningKeys(private_key, tuple(retired))
