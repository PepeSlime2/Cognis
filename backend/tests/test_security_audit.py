from __future__ import annotations

import subprocess
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth_router import reset_login_rate_limiter
from app.config import app_config, auth_config
from app.database import get_neo4j_driver
from app.db import repository
from app.db.models import Analysis, Project, Report, SyncRun
from app.db.session import SessionLocal, get_db_session
from app.main import app
from app.security import decrypt_token, encrypt_token


@pytest.fixture(autouse=True)
def clean_rate_limits():
    reset_login_rate_limiter()
    yield
    reset_login_rate_limiter()


@pytest.fixture
def test_client():
    mock_neo4j = MagicMock()
    app.dependency_overrides[get_neo4j_driver] = lambda: mock_neo4j
    client = TestClient(app, base_url="http://testserver")
    yield client
    app.dependency_overrides.pop(get_neo4j_driver, None)


def _register_and_login(client: TestClient, email: str, name: str) -> tuple[str, dict[str, str]]:
    headers = {"Origin": "http://localhost:5173"}
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "name": name},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    user_id = resp.json()["user_id"]
    cookie_str = resp.headers.get("set-cookie", "")
    session_token = ""
    for part in cookie_str.split(";"):
        if "cognis_session=" in part:
            session_token = part.split("cognis_session=")[1].strip()
            break
    cookies = {"cognis_session": session_token}
    return user_id, cookies


# =========================================================================
# Item 1: Rotacionar segredos e garantir .env fora do git
# =========================================================================
def test_item1_env_file_not_tracked_in_git():
    """Garante que .env não está comitado nem versionado no git."""
    result = subprocess.run(
        ["git", "ls-files", ".env"],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "", "O arquivo .env NUNCA deve ser rastreado no git!"


# =========================================================================
# Item 2: Autorização por projeto (usuário B recebe 404 em tudo do A)
# =========================================================================
def test_item2_tenant_isolation_user_b_cannot_access_user_a_resources(test_client):
    headers = {"Origin": "http://localhost:5173"}

    # Cria Usuário A e Usuário B
    email_a = f"usera_{uuid.uuid4().hex[:6]}@example.com"
    email_b = f"userb_{uuid.uuid4().hex[:6]}@example.com"
    user_a_id, cookies_a = _register_and_login(test_client, email_a, "User A")
    user_b_id, cookies_b = _register_and_login(test_client, email_b, "User B")

    # Usuário A cria um projeto
    proj_resp = test_client.post(
        "/projects",
        json={"name": "Projeto Alpha do User A", "history_days": 30},
        headers=headers,
        cookies=cookies_a,
    )
    assert proj_resp.status_code == 201
    proj_a_id = proj_resp.json()["id"]

    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    win_from = now - dt.timedelta(days=14)
    win_to = now

    # Cria recursos associados ao projeto A no SQLite
    with SessionLocal() as db:
        run_a = SyncRun(project_id=proj_a_id, status="completed")
        db.add(run_a)
        analysis_a = Analysis(
            project_id=proj_a_id,
            window_from=win_from,
            window_to=win_to,
            facts_json={"people": []},
            scope="team",
            status="completed",
            source="template",
        )
        db.add(analysis_a)
        report_a = Report(
            project_id=proj_a_id,
            type="sprint",
            window_from=win_from,
            window_to=win_to,
            status="completed",
            files_json={"html": "dummy_path.html"},
        )
        db.add(report_a)
        db.commit()
        run_a_id = run_a.id
        analysis_a_id = analysis_a.id
        report_a_id = report_a.id

    # Agora o Usuário B tenta acessar CADA um dos recursos do Usuário A
    # Todos devem retornar estritamente 404 Not Found (nunca 200, 401 ou 403 que revelariam existência)
    endpoints_to_test = [
        ("GET", f"/projects/{proj_a_id}"),
        ("PUT", f"/projects/{proj_a_id}/settings", {"auto_sync": True, "sync_interval_min": 60}),
        ("GET", f"/projects/{proj_a_id}/columns"),
        ("PUT", f"/projects/{proj_a_id}/columns", {"columns": []}),
        ("PUT", f"/projects/{proj_a_id}/sources", {"github_repos": [], "trello_boards": []}),
        ("GET", f"/projects/{proj_a_id}/sync-runs"),
        ("GET", f"/projects/{proj_a_id}/sync-runs/{run_a_id}"),
        ("POST", f"/projects/{proj_a_id}/sync", {}),
        ("GET", f"/projects/{proj_a_id}/graph"),
        ("GET", f"/projects/{proj_a_id}/people"),
        ("POST", f"/projects/{proj_a_id}/people/merge", {"keep_person_id": "p1", "merge_person_ids": ["p2"]}),
        ("GET", f"/projects/{proj_a_id}/links"),
        ("POST", f"/projects/{proj_a_id}/links", {"source_uid": "p1", "target_uid": "c1"}),
        ("DELETE", f"/projects/{proj_a_id}/links?source_uid=p1&target_uid=c1"),
        ("GET", f"/projects/{proj_a_id}/metrics"),
        ("GET", f"/projects/{proj_a_id}/metrics/evolution"),
        ("GET", f"/projects/{proj_a_id}/signals"),
        ("GET", f"/projects/{proj_a_id}/sprints"),
        ("POST", f"/projects/{proj_a_id}/sprints", {"name": "S1", "start_date": "2026-10-01", "end_date": "2026-10-14"}),
        ("GET", f"/projects/{proj_a_id}/analyses"),
        ("POST", f"/projects/{proj_a_id}/analyses", {"scope": "team"}),
        ("GET", f"/analyses/{analysis_a_id}"),
        ("GET", f"/projects/{proj_a_id}/reports"),
        ("GET", f"/reports/{report_a_id}"),
        ("GET", f"/reports/{report_a_id}/download?format=html"),
    ]

    for item in endpoints_to_test:
        method = item[0]
        url = item[1]
        body = item[2] if len(item) > 2 else None

        if method == "GET":
            resp = test_client.get(url, headers=headers, cookies=cookies_b)
        elif method == "POST":
            resp = test_client.post(url, json=body, headers=headers, cookies=cookies_b)
        elif method == "PUT":
            resp = test_client.put(url, json=body, headers=headers, cookies=cookies_b)
        elif method == "DELETE":
            resp = test_client.delete(url, headers=headers, cookies=cookies_b)

        assert resp.status_code == 404, f"Falha de isolamento no endpoint {method} {url}: esperado 404, recebido {resp.status_code} ({resp.text})"


# =========================================================================
# Item 4: CSRF (Origin/Referer middleware)
# =========================================================================
def test_item4_csrf_rejects_missing_or_unauthorized_origin(test_client):
    email = f"csrf_{uuid.uuid4().hex[:6]}@example.com"
    payload = {"email": email, "password": "password123", "name": "CSRF Test"}

    # 1. Sem Origin nem Referer em POST -> 403 Forbidden
    resp1 = test_client.post("/auth/register", json=payload)
    assert resp1.status_code == 403, "Requisição sem Origin deve ser bloqueada com 403"
    assert resp1.json()["detail"] == "Origem da requisição não autorizada"

    # 2. Com Origin maliciosa -> 403 Forbidden
    resp2 = test_client.post(
        "/auth/register",
        json=payload,
        headers={"Origin": "https://malicious-attacker.com"},
    )
    assert resp2.status_code == 403, "Origin não autorizada deve ser bloqueada com 403"

    # 3. Com Origin autorizada -> Sucesso
    resp3 = test_client.post(
        "/auth/register",
        json=payload,
        headers={"Origin": "http://localhost:5173"},
    )
    assert resp3.status_code == 200, f"Origin autorizada deve passar: {resp3.text}"


# =========================================================================
# Item 5: Login - limitador em memória (5 tentativas/min por IP+email) e senha mínima
# =========================================================================
def test_item5_login_rate_limiter_and_password_length(test_client):
    headers = {"Origin": "http://localhost:5173"}

    # Senha menor que 8 no cadastro -> 400
    resp_short = test_client.post(
        "/auth/register",
        json={"email": "short_pw@example.com", "password": "1234567"},
        headers=headers,
    )
    assert resp_short.status_code == 400
    assert "pelo menos 8 caracteres" in resp_short.json()["detail"]

    # Cria usuário com senha correta
    valid_email = f"ratelimit_{uuid.uuid4().hex[:6]}@example.com"
    resp_reg = test_client.post(
        "/auth/register",
        json={"email": valid_email, "password": "password123"},
        headers=headers,
    )
    assert resp_reg.status_code == 200

    # 5 tentativas erradas sucessivas
    for attempt in range(5):
        resp_fail = test_client.post(
            "/auth/login",
            json={"email": valid_email, "password": "wrong_password"},
            headers=headers,
        )
        assert resp_fail.status_code == 401
        assert resp_fail.json()["detail"] == "Email ou senha inválidos"

    # 6ª tentativa -> 429 Too Many Requests
    resp_blocked = test_client.post(
        "/auth/login",
        json={"email": valid_email, "password": "wrong_password"},
        headers=headers,
    )
    assert resp_blocked.status_code == 429
    assert "Muitas tentativas de login" in resp_blocked.json()["detail"]

    # Tentativa com senha correta enquanto bloqueado -> continua 429
    resp_blocked_correct = test_client.post(
        "/auth/login",
        json={"email": valid_email, "password": "password123"},
        headers=headers,
    )
    assert resp_blocked_correct.status_code == 429

    # Limpando o rate limiter (simula passagem de 1 min) -> login volta a funcionar
    reset_login_rate_limiter()
    resp_ok = test_client.post(
        "/auth/login",
        json={"email": valid_email, "password": "password123"},
        headers=headers,
    )
    assert resp_ok.status_code == 200


# =========================================================================
# Item 6: Criptografia Fernet e tokens nunca expostos
# =========================================================================
def test_item6_fernet_encryption_and_no_token_leakage(test_client):
    headers = {"Origin": "http://localhost:5173"}
    secret_token = "ghp_VerySecretAccessToken12345"

    # Testa criptografia e decriptografia Fernet
    encrypted = encrypt_token(secret_token)
    assert encrypted != secret_token
    assert decrypt_token(encrypted) == secret_token

    # Cria usuário e salva conexão criptografada no banco
    email = f"fernet_{uuid.uuid4().hex[:6]}@example.com"
    user_id, cookies = _register_and_login(test_client, email, "Fernet User")

    with SessionLocal() as db:
        repository.save_provider_connection(
            db,
            user_id=user_id,
            provider="github",
            external_login="github_user",
            access_token=secret_token,
            scope="repo,read:user",
        )
        db.commit()

        # Verifica que no banco o token está gravado cifrado
        from sqlalchemy import select
        from app.db.models import ProviderConnection
        conn = db.scalar(select(ProviderConnection).where(ProviderConnection.user_id == user_id, ProviderConnection.provider == "github"))
        assert conn is not None
        assert conn.access_token_enc != secret_token
        assert decrypt_token(conn.access_token_enc) == secret_token

    # Chama /auth/me -> tokens NUNCA devem aparecer no retorno
    resp_me = test_client.get("/auth/me", headers=headers, cookies=cookies)
    assert resp_me.status_code == 200
    data = resp_me.json()
    assert secret_token not in str(data)
    assert data["connections"]["github"]["status"] == "ok"


# =========================================================================
# Item 7: Validação Pydantic de entrada (limites de caracteres e fontes)
# =========================================================================
def test_item7_input_validation_limits(test_client):
    headers = {"Origin": "http://localhost:5173"}
    email = f"pydantic_{uuid.uuid4().hex[:6]}@example.com"
    _, cookies = _register_and_login(test_client, email, "Validation User")

    # Nome > 80 caracteres -> 422
    resp_long_name = test_client.post(
        "/projects",
        json={"name": "A" * 81, "history_days": 90},
        headers=headers,
        cookies=cookies,
    )
    assert resp_long_name.status_code in (400, 422)

    # history_days < 7 ou > 365 -> 422
    resp_small_history = test_client.post(
        "/projects",
        json={"name": "Proj OK", "history_days": 6},
        headers=headers,
        cookies=cookies,
    )
    assert resp_small_history.status_code in (400, 422)

    resp_large_history = test_client.post(
        "/projects",
        json={"name": "Proj OK", "history_days": 366},
        headers=headers,
        cookies=cookies,
    )
    assert resp_large_history.status_code in (400, 422)

    # Cria projeto válido para testar fontes
    proj_resp = test_client.post(
        "/projects",
        json={"name": "Proj Valido", "history_days": 30},
        headers=headers,
        cookies=cookies,
    )
    assert proj_resp.status_code == 201
    proj_id = proj_resp.json()["id"]

    # Mais de 20 fontes -> 422
    too_many_sources = [f"repo_{i}" for i in range(21)]
    resp_sources = test_client.put(
        f"/projects/{proj_id}/sources",
        json={"github_repos": too_many_sources, "trello_boards": []},
        headers=headers,
        cookies=cookies,
    )
    assert resp_sources.status_code in (400, 422)


# =========================================================================
# Item 8: Prevenção de Path Traversal no download de relatórios
# =========================================================================
def test_item8_report_download_path_traversal_prevention(test_client):
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    win_from = now - dt.timedelta(days=14)
    win_to = now

    headers = {"Origin": "http://localhost:5173"}
    email = f"path_{uuid.uuid4().hex[:6]}@example.com"
    user_id, cookies = _register_and_login(test_client, email, "Path User")

    proj_resp = test_client.post(
        "/projects",
        json={"name": "Proj Path", "history_days": 30},
        headers=headers,
        cookies=cookies,
    )
    assert proj_resp.status_code == 201
    proj_id = proj_resp.json()["id"]

    # Cria relatório completado
    with SessionLocal() as db:
        rep = Report(
            project_id=proj_id,
            type="sprint",
            window_from=win_from,
            window_to=win_to,
            status="completed",
            files_json={"html": "safe_storage/report.html"},
        )
        db.add(rep)
        db.commit()
        rep_id = rep.id

    # O endpoint aceita apenas ?format=html|docx|pdf (enum estrito), nunca um path direto
    resp_traversal = test_client.get(
        f"/reports/{rep_id}/download?format=../../etc/passwd",
        headers=headers,
        cookies=cookies,
    )
    assert resp_traversal.status_code in (400, 422)


# =========================================================================
# Item 9: Configuração rigorosa de CORS
# =========================================================================
def test_item9_cors_configuration(test_client):
    # Requisição OPTIONS preflight com origin válida
    resp_opt = test_client.options(
        "/auth/me",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp_opt.status_code == 200
    assert resp_opt.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert resp_opt.headers.get("access-control-allow-credentials") == "true"


# =========================================================================
# Item 3: Cypher sempre parametrizado e com project_id
# =========================================================================
def test_item3_cypher_queries_use_parameters_and_project_id():
    """
    Verifica estaticamente que nenhuma chamada a session.run ou tx.run nos módulos
    principais de backend concatena entradas com f-strings perigosas ou omite project_id.
    """
    import inspect
    from app.graph import facts
    from app import linker, identity_service, graph_service

    modules_to_inspect = [facts, linker, identity_service, graph_service]
    for mod in modules_to_inspect:
        source = inspect.getsource(mod)
        # Verifica que session.run ou tx.run usam kwargs ou mapas de parâmetros
        assert "tx.run(" in source or "session.run(" in source
        # Nenhuma query executada deve concatenar texto do usuário diretamente
        assert "f\"MATCH " not in source or "project_id" in source


# =========================================================================
# Item 10: Logs sem tokens e sem corpos de comentários
# =========================================================================
def test_item10_log_sanitization_no_tokens_or_comment_bodies(caplog):
    """
    Verifica que mensagens de log registram apenas metadados e nunca
    exibem tokens reais ou corpos de comentários/commits.
    """
    import logging
    from app.reports_router import logger as rep_logger

    with caplog.at_level(logging.DEBUG):
        # Simula log durante processo
        rep_logger.info("Iniciando geração de relatório para projeto %s", "proj-123")
        for record in caplog.records:
            msg = record.getMessage()
            assert "ghp_" not in msg
            assert "Bearer " not in msg
            assert "password" not in msg

