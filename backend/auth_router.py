"""
Rotas de autenticação.

GitHub:  fluxo OAuth2 clássico, tudo server-side.
  GET  /auth/github/login      -> redireciona pro GitHub
  GET  /auth/github/callback   -> GitHub chama aqui de volta com ?code=

Trello:  o Trello não faz esse "code exchange" — ele devolve o token
direto pro navegador, no fragmento da URL (#token=...). Por isso:
  GET  /auth/trello/authorize-url  -> devolve a URL que o FRONTEND deve abrir
  POST /auth/trello/token          -> o FRONTEND manda aqui o token que capturou

Sessão: um JWT em cookie httpOnly (não fica acessível via JS, então
não some por causa de disparo de XSS bobo).

As dependências get_current_user_id / get_optional_user_id são
importadas e usadas no main.py (rotas /auth/me e DELETE /auth/{provider}
vivem lá, porque precisam do Depends).
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel

from config import app_config, auth_config, github_oauth, trello_oauth
from github_collector import get_authenticated_username as get_github_username
from security import create_session_jwt, decode_session_jwt, hash_password, verify_password
from trello_collector import get_authenticated_member as get_trello_member
from user_store import UserStore

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str
    password: str
    name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/register")
def register(body: RegisterIn, response: Response):
    email = body.email.strip().lower()
    if "@" not in email or len(body.password) < 8:
        raise HTTPException(400, "Informe um email válido e uma senha com pelo menos 8 caracteres")
    with UserStore() as store:
        store.ensure_constraints()
        if store.get_local_user(email):
            raise HTTPException(409, "Este email já está cadastrado")
        user_id = store.create_local_user(email, hash_password(body.password), body.name)
    _set_session_cookie(response, user_id)
    return {"user_id": user_id, "email": email, "name": body.name}


@router.post("/login")
def login(body: LoginIn, response: Response):
    email = body.email.strip().lower()
    with UserStore() as store:
        user = store.get_local_user(email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Email ou senha inválidos")
    _set_session_cookie(response, user["id"])
    return {"user_id": user["id"], "email": user["email"], "name": user.get("name")}


def _set_session_cookie(response: Response, user_id: str) -> None:
    token = create_session_jwt(user_id)
    response.set_cookie(
        key=auth_config.session_cookie_name, value=token, httponly=True,
        secure=auth_config.cookie_secure, samesite="lax",
        max_age=auth_config.jwt_expires_minutes * 60,
    )


def get_current_user_id(cognis_session: str | None = Cookie(default=None)) -> str:
    """Dependency do FastAPI — usa em qualquer rota que exige login."""
    if not cognis_session:
        raise HTTPException(401, "Não autenticado")
    user_id = decode_session_jwt(cognis_session)
    if not user_id:
        raise HTTPException(401, "Sessão inválida ou expirada")
    return user_id


def get_optional_user_id(cognis_session: str | None = Cookie(default=None)) -> str | None:
    if not cognis_session:
        return None
    return decode_session_jwt(cognis_session)


# ---------------- GitHub ----------------

@router.get("/github/login")
def github_login(response: Response):
    state = secrets.token_urlsafe(24)
    response.set_cookie(
        key=auth_config.oauth_state_cookie_name, value=state, httponly=True,
        secure=auth_config.cookie_secure, samesite="lax", max_age=600,
    )
    url = (
        f"{github_oauth.authorize_url}?client_id={github_oauth.client_id}"
        f"&redirect_uri={github_oauth.redirect_uri}&scope={github_oauth.scope}&state={state}"
    )
    return {"authorize_url": url}


@router.get("/github/callback")
def github_callback(code: str, state: str, response: Response,
                     cognis_oauth_state: str | None = Cookie(default=None),
                     cognis_session: str | None = Cookie(default=None)):
    if not cognis_oauth_state or state != cognis_oauth_state:
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
        raise HTTPException(400, f"GitHub não retornou token: {payload}")

    username = get_github_username(access_token)

    existing_user_id = decode_session_jwt(cognis_session) if cognis_session else None
    with UserStore() as store:
        user_id = store.get_or_create_user(existing_user_id)
        store.link_provider_account(user_id=user_id, provider="github", username=username, raw_token=access_token)

    _set_session_cookie(response, user_id)
    response.delete_cookie(auth_config.oauth_state_cookie_name)
    # devolve o navegador pro frontend (ex: uma tela de configurações com ?connected=github)
    response.status_code = 302
    response.headers["Location"] = f"{app_config.frontend_url}/settings?connected=github"
    return response


# ---------------- Trello ----------------

def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@router.get("/trello/authorize-url")
def trello_authorize_url(response: Response):
    if not trello_oauth.client_id:
        raise HTTPException(500, "TRELLO_CLIENT_ID não configurado no .env")

    return_url = f"{app_config.frontend_url}/trello-callback"
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    response.set_cookie("trello_pkce_verifier", verifier, httponly=True,
                        secure=auth_config.cookie_secure, samesite="lax", max_age=600)
    response.set_cookie("trello_oauth_state", state, httponly=True,
                        secure=auth_config.cookie_secure, samesite="lax", max_age=600)
    params = {
        "client_id": trello_oauth.client_id,
        "scope": trello_oauth.scope,
        "redirect_uri": return_url,
        "response_type": "code",
        "prompt": "consent",
        "code_challenge_method": "S256",
        "code_challenge": _pkce_challenge(verifier),
    }
    return {"authorize_url": f"{trello_oauth.authorize_url}?{urlencode(params)}"}


class TrelloTokenIn(BaseModel):
    token: str


@router.get("/trello/exchange")
def trello_exchange(code: str, state: str, response: Response,
                    trello_oauth_state: str | None = Cookie(default=None),
                    trello_pkce_verifier: str | None = Cookie(default=None),
                    cognis_session: str | None = Cookie(default=None)):
    if not trello_oauth.client_id or not trello_oauth.client_secret:
        raise HTTPException(500, "TRELLO_CLIENT_ID e TRELLO_CLIENT_SECRET devem estar configurados no .env")
    if not trello_oauth_state or state != trello_oauth_state:
        raise HTTPException(400, "state inválido — inicie a conexão novamente")
    if not trello_pkce_verifier:
        raise HTTPException(400, "PKCE ausente — inicie a conexão novamente")

    token_resp = requests.post(
        trello_oauth.token_url,
        json={
            "client_id": trello_oauth.client_id,
            "client_secret": trello_oauth.client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": f"{app_config.frontend_url}/trello-callback",
            "code": code,
            "code_verifier": trello_pkce_verifier,
        },
        timeout=15,
    )
    if not token_resp.ok:
        raise HTTPException(token_resp.status_code, f"Trello recusou o código: {token_resp.text}")
    access_token = token_resp.json().get("access_token")
    if not access_token:
        raise HTTPException(400, "Trello não retornou access_token")

    member = get_trello_member(access_token)
    existing_user_id = decode_session_jwt(cognis_session) if cognis_session else None
    with UserStore() as store:
        user_id = store.get_or_create_user(existing_user_id)
        store.link_provider_account(
            user_id=user_id, provider="trello", username=member["username"],
            raw_token=access_token, name=member.get("fullName"), avatar_url=member.get("avatarUrl"),
        )

    _set_session_cookie(response, user_id)
    response.delete_cookie("trello_oauth_state")
    response.delete_cookie("trello_pkce_verifier")
    return {"connected": "trello", "username": member["username"]}


@router.post("/trello/token")
def trello_token(body: TrelloTokenIn, response: Response,
                  cognis_session: str | None = Cookie(default=None)):
    member = get_trello_member(body.token)  # valida o token contra a API do Trello

    existing_user_id = decode_session_jwt(cognis_session) if cognis_session else None
    with UserStore() as store:
        user_id = store.get_or_create_user(existing_user_id)
        store.link_provider_account(
            user_id=user_id, provider="trello", username=member["username"],
            raw_token=body.token, name=member.get("fullName"), avatar_url=member.get("avatarUrl"),
        )

    _set_session_cookie(response, user_id)
    return {"connected": "trello", "username": member["username"]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth_config.session_cookie_name)
    return {"ok": True}
