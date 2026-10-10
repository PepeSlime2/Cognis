"""
Segurança: sessão do usuário (JWT em cookie httpOnly) e criptografia
dos tokens do GitHub/Trello antes de gravar no Neo4j.

Por que criptografar o token no banco? Porque esse token dá acesso à
conta GitHub/Trello real do usuário — se o Neo4j vazar, você não quer
que ele venha em texto puro.

Gerar uma FERNET_KEY nova:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Gerar um JWT_SECRET novo:
    python -c "import secrets; print(secrets.token_hex(32))"
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets

import jwt
from cryptography.fernet import Fernet

from .config import auth_config

_fernet = Fernet(auth_config.fernet_key.encode()) if auth_config.fernet_key else None


def encrypt_token(raw_token: str) -> str:
    if not _fernet:
        raise RuntimeError("FERNET_KEY não configurada no .env")
    return _fernet.encrypt(raw_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    if not _fernet:
        raise RuntimeError("FERNET_KEY não configurada no .env")
    return _fernet.decrypt(encrypted_token.encode()).decode()


def create_session_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=auth_config.jwt_expires_minutes),
        "iat": dt.datetime.now(dt.timezone.utc),
    }
    return jwt.encode(payload, auth_config.jwt_secret, algorithm=auth_config.jwt_algorithm)


def decode_session_jwt(token: str) -> str | None:
    """Retorna o user_id do token, ou None se inválido/expirado."""
    try:
        payload = jwt.decode(token, auth_config.jwt_secret, algorithms=[auth_config.jwt_algorithm])
        return payload["sub"]
    except jwt.PyJWTError:
        return None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt_hex, digest_hex = encoded.split("$", 1)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), 310_000
        )
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
