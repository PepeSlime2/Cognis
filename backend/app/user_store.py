"""
Guarda a identidade "de login" do sistema.

Modelo:
    (:User {id, created_at})
      -[:AUTENTICADO_COMO {token_enc, connected_at}]-> (:Developer {username, source:"github"})
      -[:AUTENTICADO_COMO {token_enc, connected_at}]-> (:Developer {username, source:"trello"})

Isso resolve de brinde o problema de "GitHub e Trello têm usernames
diferentes pro mesmo humano": como os dois Developer ficam pendurados
no mesmo User, dá pra unificar produtividade/colaboração por User em
vez de por username solto.

O token nunca é gravado em texto puro (veja security.encrypt_token).
"""
from __future__ import annotations

import datetime as dt
import uuid

from neo4j import GraphDatabase

from .config import neo4j_config
from .security import decrypt_token, encrypt_token


class UserStore:
    def __init__(self) -> None:
        self._driver = GraphDatabase.driver(
            neo4j_config.uri, auth=(neo4j_config.user, neo4j_config.password)
        )

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "UserStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def ensure_constraints(self) -> None:
        with self._driver.session() as session:
            session.run("CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE")
            session.run("CREATE CONSTRAINT user_email IF NOT EXISTS FOR (u:User) REQUIRE u.email IS UNIQUE")

    def create_local_user(self, email: str, password_hash: str, name: str | None = None) -> str:
        user_id = str(uuid.uuid4())
        with self._driver.session() as session:
            session.run(
                "CREATE (u:User {id: $id, email: $email, password_hash: $password_hash, name: $name, created_at: $created_at})",
                id=user_id, email=email, password_hash=password_hash, name=name,
                created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            )
        return user_id

    def get_local_user(self, email: str) -> dict | None:
        with self._driver.session() as session:
            record = session.run(
                "MATCH (u:User {email: $email}) RETURN u.id AS id, u.email AS email, u.name AS name, u.password_hash AS password_hash",
                email=email,
            ).single()
        return dict(record) if record else None

    def get_or_create_user(self, user_id: str | None) -> str:
        """Se user_id existir e for válido, retorna ele mesmo. Senão, cria um novo User."""
        if user_id:
            with self._driver.session() as session:
                exists = session.run("MATCH (u:User {id: $id}) RETURN u.id AS id", id=user_id).single()
            if exists:
                return user_id

        new_id = str(uuid.uuid4())
        with self._driver.session() as session:
            session.run(
                "CREATE (u:User {id: $id, created_at: $created_at})",
                id=new_id, created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            )
        return new_id

    def link_provider_account(self, user_id: str, provider: str, username: str,
                               raw_token: str, name: str | None = None, avatar_url: str | None = None) -> None:
        token_enc = encrypt_token(raw_token)
        with self._driver.session() as session:
            session.run(
                """
                MATCH (u:User {id: $user_id})
                MERGE (d:Developer {username: $username})
                SET d.source = $provider, d.name = coalesce($name, d.name),
                    d.avatar_url = coalesce($avatar_url, d.avatar_url)
                MERGE (u)-[rel:AUTENTICADO_COMO]->(d)
                SET rel.token_enc = $token_enc,
                    rel.connected_at = $connected_at,
                    rel.provider = $provider
                """,
                user_id=user_id, username=username, provider=provider,
                name=name, avatar_url=avatar_url, token_enc=token_enc,
                connected_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            )

    def get_provider_token(self, user_id: str, provider: str) -> str | None:
        with self._driver.session() as session:
            record = session.run(
                """
                MATCH (u:User {id: $user_id})-[rel:AUTENTICADO_COMO {provider: $provider}]->(:Developer)
                RETURN rel.token_enc AS token_enc
                """,
                user_id=user_id, provider=provider,
            ).single()
        if not record:
            return None
        return decrypt_token(record["token_enc"])

    def get_connections(self, user_id: str) -> dict:
        with self._driver.session() as session:
            records = session.run(
                """
                MATCH (u:User {id: $user_id})-[rel:AUTENTICADO_COMO]->(d:Developer)
                RETURN rel.provider AS provider, d.username AS username, rel.connected_at AS connected_at
                """,
                user_id=user_id,
            )
            return {r["provider"]: {"username": r["username"], "connected_at": r["connected_at"]} for r in records}

    def disconnect_provider(self, user_id: str, provider: str) -> None:
        """Remove só o vínculo de login/token — o Developer e o histórico dele no grafo ficam intactos."""
        with self._driver.session() as session:
            session.run(
                """
                MATCH (u:User {id: $user_id})-[rel:AUTENTICADO_COMO {provider: $provider}]->(:Developer)
                DELETE rel
                """,
                user_id=user_id, provider=provider,
            )
