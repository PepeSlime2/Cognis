from __future__ import annotations

import datetime as dt

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import trello_oauth
from .db.models import ProviderConnection
from .security import decrypt_token, encrypt_token

REFRESH_BEFORE_EXPIRY = dt.timedelta(minutes=5)


class TrelloReconnectRequired(Exception):
    pass


class TrelloTokenRefreshError(Exception):
    pass


def refresh_if_needed(
    session: Session,
    user_id: str,
    now: dt.datetime | None = None,
) -> str | None:
    connection = session.scalar(
        select(ProviderConnection)
        .where(
            ProviderConnection.user_id == user_id,
            ProviderConnection.provider == "trello",
        )
        .with_for_update()
    )
    if connection is None:
        return None
    if connection.status == "needs_reconnect":
        raise TrelloReconnectRequired

    current_time = now or dt.datetime.now(dt.timezone.utc)
    if (
        connection.expires_at is not None
        and connection.expires_at > current_time + REFRESH_BEFORE_EXPIRY
    ):
        return decrypt_token(connection.access_token_enc)

    if not connection.refresh_token_enc:
        _require_reconnect(session, connection)

    refresh_token = decrypt_token(connection.refresh_token_enc)
    try:
        response = requests.post(
            trello_oauth.token_url,
            json={
                "grant_type": "refresh_token",
                "client_id": trello_oauth.client_id,
                "client_secret": trello_oauth.client_secret,
                "refresh_token": refresh_token,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise TrelloTokenRefreshError from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not response.ok:
        if isinstance(payload, dict) and payload.get("error") == "invalid_grant":
            _require_reconnect(session, connection)
        raise TrelloTokenRefreshError

    access_token = payload.get("access_token") if isinstance(payload, dict) else None
    new_refresh_token = payload.get("refresh_token") if isinstance(payload, dict) else None
    expires_in = payload.get("expires_in") if isinstance(payload, dict) else None
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(new_refresh_token, str)
        or not new_refresh_token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or expires_in <= 0
    ):
        raise TrelloTokenRefreshError

    new_access_token_enc = encrypt_token(access_token)
    new_refresh_token_enc = encrypt_token(new_refresh_token)
    refreshed_at = dt.datetime.now(dt.timezone.utc)
    connection.access_token_enc = new_access_token_enc
    connection.refresh_token_enc = new_refresh_token_enc
    connection.expires_at = refreshed_at + dt.timedelta(seconds=expires_in)
    connection.status = "ok"
    session.commit()
    return access_token


def _require_reconnect(
    session: Session,
    connection: ProviderConnection,
) -> None:
    connection.status = "needs_reconnect"
    session.commit()
    raise TrelloReconnectRequired
