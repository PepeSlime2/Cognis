from __future__ import annotations

import os
from pathlib import Path
import uuid
import pytest
from fastapi.testclient import TestClient

from app import config, database, main
from app.db import session as db_session_module
from app.db.models import (
    Analysis,
    ColumnMapping,
    MetricSnapshot,
    PersonOverride,
    Project,
    ProjectSource,
    Report,
    Sprint,
    SyncRun,
    User,
    utc_now,
)


def register_and_login(client: TestClient, email: str) -> str:
    client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "name": "LGPD Tester"},
        headers={"Origin": config.app_config.frontend_url},
    )
    res = client.post(
        "/auth/login",
        json={"email": email, "password": "Password123!"},
        headers={"Origin": config.app_config.frontend_url},
    )
    assert res.status_code == 200
    return res.json()["user_id"]


def test_delete_project_lgpd_removes_files_sqlite_and_neo4j():
    with TestClient(main.app) as client:
        uid_a = f"lgpd_owner_{uuid.uuid4().hex[:8]}@example.com"
        user_id = register_and_login(client, uid_a)

        project_id = f"proj-lgpd-{uuid.uuid4().hex[:8]}"

        # 1. Inserir dados no SQLite
        with db_session_module.SessionLocal() as session:
            proj = Project(
                id=project_id,
                user_id=user_id,
                name="Projeto LGPD Delete",
                timezone="America/Sao_Paulo",
            )
            session.add(proj)
            session.commit()

            source = ProjectSource(
                id=str(uuid.uuid4()),
                project_id=project_id,
                provider="github",
                external_id="owner/repo-lgpd",
                display_name="repo-lgpd",
            )
            session.add(source)

            col = ColumnMapping(
                project_id=project_id,
                column_uid="col-1",
                name="A Fazer",
                category="todo",
                source="manual",
            )
            session.add(col)

            sprint = Sprint(
                id=str(uuid.uuid4()),
                project_id=project_id,
                name="Sprint 1",
                start_date=utc_now(),
                end_date=utc_now(),
            )
            session.add(sprint)

            override = PersonOverride(
                project_id=project_id,
                person_uid="person-1",
                display_name="Dev LGPD",
                excluded=False,
            )
            session.add(override)

            sync = SyncRun(
                id=str(uuid.uuid4()),
                project_id=project_id,
                status="success",
                started_at=utc_now(),
                finished_at=utc_now(),
            )
            session.add(sync)

            snapshot = MetricSnapshot(
                id=str(uuid.uuid4()),
                project_id=project_id,
                window_from=utc_now(),
                window_to=utc_now(),
                config_hash="test-hash",
                data_version="v1",
                bundle_json={"density": 0.5},
            )
            session.add(snapshot)

            analysis = Analysis(
                id=str(uuid.uuid4()),
                project_id=project_id,
                scope="team",
                window_from=utc_now(),
                window_to=utc_now(),
                status="done",
                facts_json={},
                result_json={},
            )
            session.add(analysis)
            session.commit()

            # Criar arquivos reais em storage/reports/{project_id}/report-1/
            report_dir = Path("storage/reports") / project_id / "report-1"
            report_dir.mkdir(parents=True, exist_ok=True)
            html_file = report_dir / "report.html"
            docx_file = report_dir / "report.docx"
            pdf_file = report_dir / "report.pdf"
            model_file = report_dir / "report_model.json"
            html_file.write_text("<html>Report</html>", encoding="utf-8")
            docx_file.write_bytes(b"PK00mockdocx")
            pdf_file.write_bytes(b"%PDF-1.4 mock")
            model_file.write_text("{}", encoding="utf-8")

            report = Report(
                id=str(uuid.uuid4()),
                project_id=project_id,
                type="sprint",
                window_from=utc_now(),
                window_to=utc_now(),
                status="done",
                model_json_path=str(model_file),
                files_json={
                    "html": str(html_file),
                    "docx": str(docx_file),
                    "pdf": str(pdf_file),
                },
                analysis_id=analysis.id,
            )
            session.add(report)
            session.commit()

        # 2. Inserir nós no Neo4j com project_id se o driver estiver ativo
        neo4j_driver = getattr(main.app.state, "neo4j_driver", None)
        has_neo4j = False
        if neo4j_driver:
            try:
                with neo4j_driver.session() as n_session:
                    # Criar nós de teste com project_id
                    n_session.run(
                        "CREATE (p:Person {uid: $puid, project_id: $pid, name: 'Dev 1'}) "
                        "CREATE (t:Task {uid: $tuid, project_id: $pid, title: 'Task 1'}) "
                        "CREATE (p)-[:ATRIBUIDO_A {project_id: $pid}]->(t)",
                        puid=f"person-{project_id}",
                        tuid=f"task-{project_id}",
                        pid=project_id,
                    ).consume()

                    # Verificar que nós foram criados
                    cnt_before = n_session.run(
                        "MATCH (n {project_id: $pid}) RETURN count(n) AS cnt",
                        pid=project_id,
                    ).single()["cnt"]
                    assert cnt_before == 2
                    has_neo4j = True
            except Exception:
                has_neo4j = False

        # 3. Executar DELETE /projects/{project_id}
        res_del = client.delete(
            f"/projects/{project_id}",
            headers={"Origin": config.app_config.frontend_url},
        )
        assert res_del.status_code == 204

        # 4. Verificar que arquivos foram apagados do disco
        assert not (Path("storage/reports") / project_id).exists()
        assert not html_file.exists()
        assert not docx_file.exists()
        assert not pdf_file.exists()
        assert not model_file.exists()

        # 5. Verificar que contagem de nós no Neo4j é 0 (Aceite F10.4)
        if has_neo4j and neo4j_driver:
            with neo4j_driver.session() as n_session:
                cnt_after = n_session.run(
                    "MATCH (n {project_id: $pid}) RETURN count(n) AS cnt",
                    pid=project_id,
                ).single()["cnt"]
                assert cnt_after == 0, f"Esperado 0 nós com project_id={project_id}, obtido {cnt_after}"

        # 6. Verificar que registros SQLite foram apagados
        with db_session_module.SessionLocal() as session:
            assert session.query(Project).filter(Project.id == project_id).first() is None
            assert session.query(ProjectSource).filter(ProjectSource.project_id == project_id).count() == 0
            assert session.query(ColumnMapping).filter(ColumnMapping.project_id == project_id).count() == 0
            assert session.query(Sprint).filter(Sprint.project_id == project_id).count() == 0
            assert session.query(PersonOverride).filter(PersonOverride.project_id == project_id).count() == 0
            assert session.query(SyncRun).filter(SyncRun.project_id == project_id).count() == 0
            assert session.query(MetricSnapshot).filter(MetricSnapshot.project_id == project_id).count() == 0
            assert session.query(Analysis).filter(Analysis.project_id == project_id).count() == 0
            assert session.query(Report).filter(Report.project_id == project_id).count() == 0


def test_delete_project_isolation_user_b_cannot_delete_user_a():
    with TestClient(main.app) as client:
        uid_a = f"owner_a_{uuid.uuid4().hex[:8]}@example.com"
        uid_b = f"intruder_b_{uuid.uuid4().hex[:8]}@example.com"

        user_a_id = register_and_login(client, uid_a)
        proj_a_id = f"proj-a-{uuid.uuid4().hex[:8]}"

        with db_session_module.SessionLocal() as session:
            proj = Project(
                id=proj_a_id,
                user_id=user_a_id,
                name="Projeto Privado A",
                timezone="America/Sao_Paulo",
            )
            session.add(proj)
            session.commit()

        # Login como Usuário B
        client.post(
            "/auth/register",
            json={"email": uid_b, "password": "Password123!", "name": "User B"},
            headers={"Origin": config.app_config.frontend_url},
        )
        client.post(
            "/auth/login",
            json={"email": uid_b, "password": "Password123!"},
            headers={"Origin": config.app_config.frontend_url},
        )

        # Usuário B tenta deletar projeto de A
        res = client.delete(
            f"/projects/{proj_a_id}",
            headers={"Origin": config.app_config.frontend_url},
        )
        assert res.status_code == 404

        # Projeto de A continua existindo
        with db_session_module.SessionLocal() as session:
            assert session.query(Project).filter(Project.id == proj_a_id).first() is not None
