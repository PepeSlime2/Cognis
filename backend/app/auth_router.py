"""
Rotas de autenticação.

GitHub:  fluxo OAuth2 clássico, tudo server-side.
  GET  /auth/github/login      -> redireciona pro GitHub
  GET  /auth/github/callback   -> GitHub chama aqui de volta com ?code=

Trello: fluxo OAuth2 com PKCE e troca do código no backend.
  GET  /auth/trello/authorize-url  -> devolve a URL que o FRONTEND deve abrir

Sessão: um JWT em cookie httpOnly (não fica acessível via JS, então
não some por causa de disparo de XSS bobo).

Os fluxos de conexão OAuth exigem uma sessão autenticada.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets
from urllib.parse import urlencode

import requests
import threading
import time
from collections import defaultdict
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import app_config, auth_config, github_oauth, trello_oauth
from .db import repository
from .db.models import User
from .db.session import get_db_session
from .github_collector import get_authenticated_username as get_github_username
from .security import create_session_jwt, decode_session_jwt, hash_password, verify_password
from .trello_collector import get_authenticated_member as get_trello_member

router = APIRouter(prefix="/auth", tags=["auth"])

# Limitador de tentativas de login em memória (SPEC §13.1 item 5: 5 tentativas/min por IP+email)
_login_attempts: dict[tuple[str, str], list[float]] = defaultdict(list)
_login_lock = threading.Lock()
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 60.0


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def check_login_rate_limit(client_ip: str, email: str) -> None:
    now = time.monotonic()
    key = (client_ip, email.strip().lower())
    with _login_lock:
        attempts = [t for t in _login_attempts[key] if now - t < LOGIN_WINDOW_SECONDS]
        _login_attempts[key] = attempts
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail="Muitas tentativas de login. Aguarde um minuto antes de tentar novamente.",
            )


def record_failed_login(client_ip: str, email: str) -> None:
    now = time.monotonic()
    key = (client_ip, email.strip().lower())
    with _login_lock:
        attempts = [t for t in _login_attempts[key] if now - t < LOGIN_WINDOW_SECONDS]
        attempts.append(now)
        _login_attempts[key] = attempts


def clear_failed_logins(client_ip: str, email: str) -> None:
    key = (client_ip, email.strip().lower())
    with _login_lock:
        _login_attempts.pop(key, None)


def reset_login_rate_limiter() -> None:
    """Limpa o histórico de tentativas (usado em testes)."""
    with _login_lock:
        _login_attempts.clear()


class RegisterIn(BaseModel):
    email: str
    password: str
    name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/register")
def register(
    body: RegisterIn,
    response: Response,
    db_session: Session = Depends(get_db_session),
):
    email = body.email.strip().lower()
    if "@" not in email or len(body.password) < 8:
        raise HTTPException(400, "Informe um email válido e uma senha com pelo menos 8 caracteres")
    if body.name is not None and len(body.name) > 80:
        raise HTTPException(400, "O nome deve ter no máximo 80 caracteres")
    user = db_session.scalar(select(User).where(User.email == email))
    if user is not None:
        raise HTTPException(409, "Este email já está cadastrado")
    user = User(email=email, password_hash=hash_password(body.password), name=body.name)
    db_session.add(user)
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        raise HTTPException(409, "Este email já está cadastrado") from None
    _set_session_cookie(response, user.id)
    return {"user_id": user.id, "email": email, "name": user.name}


@router.post("/login")
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db_session: Session = Depends(get_db_session),
):
    client_ip = _get_client_ip(request)
    email = body.email.strip().lower()

    check_login_rate_limit(client_ip, email)

    user = db_session.scalar(select(User).where(User.email == email))
    if (
        user is None
        or user.password_hash is None
        or not verify_password(body.password, user.password_hash)
    ):
        record_failed_login(client_ip, email)
        raise HTTPException(401, "Email ou senha inválidos")

    clear_failed_logins(client_ip, email)
    _set_session_cookie(response, user.id)
    return {"user_id": user.id, "email": user.email, "name": user.name}


def _set_session_cookie(response: Response, user_id: str) -> None:
    token = create_session_jwt(user_id)
    response.set_cookie(
        key=auth_config.session_cookie_name, value=token, httponly=True,
        secure=auth_config.cookie_secure, samesite="lax",
        max_age=auth_config.jwt_expires_minutes * 60,
    )


def get_current_user_id(
    cognis_session: str | None = Cookie(default=None),
    db_session: Session = Depends(get_db_session),
) -> str:
    """Dependency do FastAPI — usa em qualquer rota que exige login."""
    if not cognis_session:
        raise HTTPException(401, "Não autenticado")
    user_id = decode_session_jwt(cognis_session)
    if not user_id or db_session.get(User, user_id) is None:
        raise HTTPException(401, "Sessão inválida ou expirada")
    return user_id


def get_optional_user_id(cognis_session: str | None = Cookie(default=None)) -> str | None:
    if not cognis_session:
        return None
    return decode_session_jwt(cognis_session)


def _oauth_user_binding(user_id: str, state: str) -> str:
    message = f"{user_id}:{state}".encode()
    return hmac.new(auth_config.jwt_secret.encode(), message, hashlib.sha256).hexdigest()


# ---------------- GitHub ----------------

@router.get("/github/login")
def github_login(
    response: Response,
    user_id: str = Depends(get_current_user_id),
):
    state = secrets.token_urlsafe(24)
    response.set_cookie(
        key=auth_config.oauth_state_cookie_name, value=state, httponly=True,
        secure=auth_config.cookie_secure, samesite="lax", max_age=600,
    )
    response.set_cookie(
        key="cognis_oauth_user",
        value=_oauth_user_binding(user_id, state),
        httponly=True,
        secure=auth_config.cookie_secure,
        samesite="lax",
        max_age=600,
    )
    params = {
        'client_id': github_oauth.client_id,
        'redirect_uri': github_oauth.redirect_uri,
        'scope': github_oauth.scope,
        'state': state,
    }
    url = f"{github_oauth.authorize_url}?{urlencode(params)}"
    return {"authorize_url": url}


@router.get("/github/callback")
def github_callback(code: str, state: str, response: Response,
                     cognis_oauth_state: str | None = Cookie(default=None),
                     cognis_oauth_user: str | None = Cookie(default=None),
                     user_id: str = Depends(get_current_user_id),
                     db_session: Session = Depends(get_db_session)):
    if (
        not cognis_oauth_state
        or state != cognis_oauth_state
        or not cognis_oauth_user
        or not hmac.compare_digest(
            cognis_oauth_user, _oauth_user_binding(user_id, state)
        )
    ):
        raise HTTPException(400, "state inválido (possível CSRF) — tente conectar de novo")

    token_resp = requests.post(
        github_oauth.token_url,
        headers={"Accept": "application/json"},
        data={
            "client_id": github_oauth.client_id,
            "client_secret": github_oauth.client_secret,
            "code": code,
            "redirect_uri": github_oauth.redirect_uri,
        },
        timeout=15,
    )
    token_resp.raise_for_status()
    payload = token_resp.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise HTTPException(400, "GitHub não retornou um token de acesso válido")

    username = get_github_username(access_token)

    repository.save_provider_connection(
        db_session,
        user_id=user_id,
        provider="github",
        external_login=username,
        access_token=access_token,
        scope=github_oauth.scope,
    )
    db_session.commit()

    response.delete_cookie(auth_config.oauth_state_cookie_name)
    response.delete_cookie("cognis_oauth_user")
    # devolve o navegador pro frontend (ex: uma tela de configurações com ?connected=github)
    response.status_code = 302
    response.headers["Location"] = f"{app_config.frontend_url}/settings?connected=github"
    return response


# ---------------- Trello ----------------

def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _clean_workspace_id(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("ari:cloud:trello::workspace/"):
        return cleaned.split("ari:cloud:trello::workspace/", 1)[1].strip()
    if "/w/" in cleaned:
        return cleaned.split("/w/", 1)[1].split("/")[0].strip()
    return cleaned.strip("/")


@router.get("/trello/authorize-url")
def trello_authorize_url(
    response: Response,
    user_id: str = Depends(get_current_user_id),
):
    if not trello_oauth.client_id:
        raise HTTPException(500, "TRELLO_CLIENT_ID não configurado no .env")

    return_url = f"{app_config.frontend_url}/trello-callback"
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    response.set_cookie("trello_pkce_verifier", verifier, httponly=True,
                        secure=auth_config.cookie_secure, samesite="lax", max_age=600)
    response.set_cookie("trello_oauth_state", state, httponly=True,
                        secure=auth_config.cookie_secure, samesite="lax", max_age=600)
    response.set_cookie(
        "trello_oauth_user",
        value=_oauth_user_binding(user_id, state),
        httponly=True,
        secure=auth_config.cookie_secure,
        samesite="lax",
        max_age=600,
    )
    params = {
        "client_id": trello_oauth.client_id,
        "scope": trello_oauth.scope,
        "redirect_uri": return_url,
        "response_type": "code",
        "state": state,
        "prompt": "consent",
        "code_challenge_method": "S256",
        "code_challenge": _pkce_challenge(verifier),
    }
    workspace_id = _clean_workspace_id(getattr(trello_oauth, "workspace_id", "") or "")
    if workspace_id:
        params["resource"] = f"ari:cloud:trello::workspace/{workspace_id}"
    return {"authorize_url": f"{trello_oauth.authorize_url}?{urlencode(params)}"}


@router.get("/trello/exchange")
def trello_exchange(code: str, state: str, response: Response,
                    trello_oauth_state: str | None = Cookie(default=None),
                    trello_oauth_user: str | None = Cookie(default=None),
                    trello_pkce_verifier: str | None = Cookie(default=None),
                    user_id: str = Depends(get_current_user_id),
                    db_session: Session = Depends(get_db_session)):
    if not trello_oauth.client_id or not trello_oauth.client_secret:
        raise HTTPException(500, "TRELLO_CLIENT_ID e TRELLO_CLIENT_SECRET devem estar configurados no .env")
    if (
        not trello_oauth_state
        or state != trello_oauth_state
        or not trello_oauth_user
        or not hmac.compare_digest(
            trello_oauth_user, _oauth_user_binding(user_id, state)
        )
    ):
        raise HTTPException(400, "state inválido — inicie a conexão novamente")
    if not trello_pkce_verifier:
        raise HTTPException(400, "PKCE ausente — inicie a conexão novamente")

    token_payload = {
        "client_id": trello_oauth.client_id,
        "client_secret": trello_oauth.client_secret,
        "grant_type": "authorization_code",
        "redirect_uri": f"{app_config.frontend_url}/trello-callback",
        "code": code,
        "code_verifier": trello_pkce_verifier,
    }
    workspace_id = _clean_workspace_id(getattr(trello_oauth, "workspace_id", "") or "")
    if workspace_id:
        token_payload["resource"] = f"ari:cloud:trello::workspace/{workspace_id}"

    token_resp = requests.post(
        trello_oauth.token_url,
        json=token_payload,
        timeout=15,
    )
    if not token_resp.ok:
        raise HTTPException(token_resp.status_code, "Trello recusou o código de autorização")
    payload = token_resp.json()
    access_token = payload.get("access_token") if isinstance(payload, dict) else None
    refresh_token = payload.get("refresh_token") if isinstance(payload, dict) else None
    expires_in = payload.get("expires_in") if isinstance(payload, dict) else None
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or expires_in <= 0
    ):
        raise HTTPException(502, "Trello não retornou credenciais válidas")

    member = get_trello_member(access_token)
    repository.save_provider_connection(
        db_session,
        user_id=user_id,
        provider="trello",
        external_login=member["username"],
        access_token=access_token,
        display_name=member.get("fullName"),
        avatar_url=member.get("avatarUrl"),
        scope=payload.get("scope", trello_oauth.scope),
        refresh_token=refresh_token,
        expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=expires_in),
    )
    db_session.commit()

    response.delete_cookie("trello_oauth_state")
    response.delete_cookie("trello_oauth_user")
    response.delete_cookie("trello_pkce_verifier")
    return {"connected": "trello", "username": member["username"]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth_config.session_cookie_name)
    return {"ok": True}
