"""
Configuração central do backend do COGNIS.

Lida do ambiente (.env). Veja .env.example.
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user: str = os.getenv("NEO4J_USER", "neo4j")
    password: str = os.getenv("NEO4J_PASSWORD", "senha")


@dataclass(frozen=True)
class GitHubOAuthConfig:
    client_id: str = os.getenv("GITHUB_CLIENT_ID", "")
    client_secret: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    # URL do SEU backend que o GitHub deve chamar de volta
    redirect_uri: str = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback")
    scope: str = "read:user repo"
    authorize_url: str = "https://github.com/login/oauth/authorize"
    token_url: str = "https://github.com/login/oauth/access_token"
    api_url: str = "https://api.github.com"


@dataclass(frozen=True)
class TrelloOAuthConfig:
    key: str = os.getenv("TRELLO_KEY", "")
    app_name: str = os.getenv("TRELLO_APP_NAME", "COGNIS")
    client_id: str = os.getenv("TRELLO_CLIENT_ID", "")
    client_secret: str = os.getenv("TRELLO_CLIENT_SECRET", "")
    scope: str = os.getenv(
        "TRELLO_OAUTH_SCOPE",
        "read:member:trello read:board:trello write:board:trello offline_access",
    )
    authorize_url: str = "https://auth.atlassian.com/authorize"
    token_url: str = "https://auth.atlassian.com/oauth/token"
    api_url: str = "https://api.trello.com/1"


@dataclass(frozen=True)
class AuthConfig:
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = int(os.getenv("JWT_EXPIRES_MINUTES", "10080"))  # 7 dias
    # chave Fernet (32 bytes url-safe base64) pra criptografar tokens de terceiros no banco
    fernet_key: str = os.getenv("FERNET_KEY", "")
    session_cookie_name: str = "cognis_session"
    oauth_state_cookie_name: str = "cognis_oauth_state"
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"


@dataclass(frozen=True)
class AppConfig:
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:5173")


neo4j_config = Neo4jConfig()
github_oauth = GitHubOAuthConfig()
trello_oauth = TrelloOAuthConfig()
auth_config = AuthConfig()
app_config = AppConfig()
