from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Adicionar diretório backend ao sys.path para permitir imports da aplicação
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from neo4j import Driver
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import create_neo4j_driver
from app.db.graph_schema import ensure_graph_schema
from app.db.models import (
    Base,
    ColumnMapping,
    PersonOverride,
    Project,
    ProjectSource,
    Sprint,
    User,
    utc_now,
)
from app.db.session import SessionLocal, create_database
from app.metrics.windows import parse_window
from app.neo4j_v2_writer import Neo4jV2Writer, make_uid

DEMO_PROJECT_ID = "demo-cognis-project"
DEMO_PROJECT_NAME = "Demo COGNIS"
DEMO_TIMEZONE = "America/Sao_Paulo"
DEMO_PROVIDER = "demo"


def clear_demo_neo4j(driver: Driver, project_id: str) -> int:
    """Remove todos os nós e relações do projeto no Neo4j com paginação LGPD."""
    query = """
    MATCH (n {project_id: $project_id})
    WITH n LIMIT 5000
    DETACH DELETE n
    RETURN count(n) AS deleted
    """
    total_deleted = 0
    with driver.session() as session:
        while True:
            result = session.run(query, project_id=project_id)
            record = result.single()
            deleted = record["deleted"] if record else 0
            total_deleted += deleted
            if deleted == 0:
                break
    return total_deleted


def ensure_demo_user(session: Session, email: str = "demo@cognis.local") -> User:
    """Recupera ou cria o usuário demo no SQLite."""
    create_database()
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            name="Demo User",
            password_hash=None,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


def seed_demo(
    driver: Driver,
    session: Session,
    user_id: str | None = None,
    reset: bool = True,
) -> dict[str, Any]:
    """
    Cria ou reinicializa o projeto Demo COGNIS com 6 pessoas e os 5 padrões plantados
    de acordo com SPEC §15.2.
    """
    create_database()
    ensure_graph_schema(driver)
    writer = Neo4jV2Writer(driver)
    tz = ZoneInfo(DEMO_TIMEZONE)

    if user_id is None:
        user = ensure_demo_user(session)
        user_id = user.id

    # 1. Reset / Limpeza se solicitado
    if reset:
        clear_demo_neo4j(driver, DEMO_PROJECT_ID)
        existing_proj = session.get(Project, DEMO_PROJECT_ID)
        if existing_proj is not None:
            session.delete(existing_proj)
            session.commit()

    # 2. Criar Projeto no SQLite
    project = session.get(Project, DEMO_PROJECT_ID)
    if project is None:
        project = Project(
            id=DEMO_PROJECT_ID,
            user_id=user_id,
            name=DEMO_PROJECT_NAME,
            timezone=DEMO_TIMEZONE,
            history_days=90,
            auto_sync=False,
            sync_interval_min=60,
            settings_json={},
        )
        session.add(project)
        session.commit()

    # 3. Criar Sprints no SQLite (3 sprints de 14 dias cada)
    sprint_defs = [
        ("Sprint 1", "2026-01-05", "2026-01-18"),
        ("Sprint 2", "2026-01-19", "2026-02-01"),
        ("Sprint 3", "2026-02-02", "2026-02-15"),
    ]
    created_sprints: list[Sprint] = []
    for idx, (s_name, s_from, s_to) in enumerate(sprint_defs, start=1):
        w = parse_window(s_from, s_to, timezone=DEMO_TIMEZONE)
        sprint_id = f"demo-sprint-{idx}"
        sprint = session.get(Sprint, sprint_id)
        if sprint is None:
            sprint = Sprint(
                id=sprint_id,
                project_id=DEMO_PROJECT_ID,
                name=s_name,
                start_date=w.start_utc,
                end_date=w.end_utc,
            )
            session.add(sprint)
        else:
            sprint.start_date = w.start_utc
            sprint.end_date = w.end_utc
        created_sprints.append(sprint)

    # 4. Criar Colunas e Mapeamentos no SQLite
    col_defs = [
        ("demo-col-backlog", "Backlog", "backlog"),
        ("demo-col-todo", "A Fazer", "todo"),
        ("demo-col-doing", "Em Andamento", "doing"),
        ("demo-col-review", "Em Revisão", "review"),
        ("demo-col-done", "Concluído", "done"),
    ]
    for c_id, c_name, c_cat in col_defs:
        c_uid = make_uid(DEMO_PROJECT_ID, "column", DEMO_PROVIDER, c_id)
        mapping = session.get(ColumnMapping, (DEMO_PROJECT_ID, c_uid))
        if mapping is None:
            mapping = ColumnMapping(
                project_id=DEMO_PROJECT_ID,
                column_uid=c_uid,
                name=c_name,
                category=c_cat,
                source="auto",
            )
            session.add(mapping)

    # Fontes de projeto
    sources = [
        ("demo", "cognis-team/cognis-platform", "Repositório Demo"),
        ("demo", "demo-board-1", "Quadro Demo"),
    ]
    for p_prov, p_ext, p_name in sources:
        src = session.scalar(
            select(ProjectSource).where(
                ProjectSource.project_id == DEMO_PROJECT_ID,
                ProjectSource.provider == p_prov,
                ProjectSource.external_id == p_ext,
            )
        )
        if src is None:
            src = ProjectSource(
                project_id=DEMO_PROJECT_ID,
                provider=p_prov,
                external_id=p_ext,
                display_name=p_name,
                enabled=True,
            )
            session.add(src)

    session.commit()

    # ==========================================
    # 5. Criar Nós no Neo4j
    # ==========================================
    # 6 Pessoas
    people_data = [
        ("ana", "Ana Silva", False, "backend"),
        ("bruno", "Bruno Costa", False, "backend"),
        ("diego", "Diego Souza", False, "backend"),
        ("carla", "Carla Moraes", False, "frontend"),
        ("elisa", "Elisa Santos", False, "frontend"),
        ("felipe", "Felipe Lima", False, "devops"),
    ]

    person_nodes = []
    account_nodes = []
    tem_conta_rels = []

    for handle, name, is_bot, role in people_data:
        p_uid = make_uid(DEMO_PROJECT_ID, "person", "cognis", handle)
        person_nodes.append({
            "uid": p_uid,
            "project_id": DEMO_PROJECT_ID,
            "display_name": name,
            "excluded": False,
        })

        acc_uid = make_uid(DEMO_PROJECT_ID, "account", DEMO_PROVIDER, handle)
        account_nodes.append({
            "uid": acc_uid,
            "project_id": DEMO_PROJECT_ID,
            "provider": DEMO_PROVIDER,
            "login": handle,
            "display_name": name,
            "avatar_url": None,
            "is_bot": is_bot,
            "linked": True,
            "email_hash": None,
        })

        tem_conta_rels.append({
            "source_uid": p_uid,
            "target_uid": acc_uid,
            "properties": {},
        })

    writer.upsert_nodes(DEMO_PROJECT_ID, "Person", person_nodes)
    writer.upsert_nodes(DEMO_PROJECT_ID, "Account", account_nodes)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Person", "TEM_CONTA", "Account", tem_conta_rels)

    # Repositório e Board
    repo_uid = make_uid(DEMO_PROJECT_ID, "repo", DEMO_PROVIDER, "cognis-platform")
    writer.upsert_nodes(DEMO_PROJECT_ID, "Repo", [{
        "uid": repo_uid,
        "project_id": DEMO_PROJECT_ID,
        "full_name": "cognis-team/cognis-platform",
        "url": "https://github.com/cognis-team/cognis-platform",
    }])

    board_uid = make_uid(DEMO_PROJECT_ID, "board", DEMO_PROVIDER, "demo-board-1")
    writer.upsert_nodes(DEMO_PROJECT_ID, "Board", [{
        "uid": board_uid,
        "project_id": DEMO_PROJECT_ID,
        "name": "Quadro de Engenharia",
        "url": "https://trello.com/b/demo-board-1",
    }])

    # Colunas
    column_nodes = []
    col_board_rels = []
    for pos, (c_id, c_name, c_cat) in enumerate(col_defs):
        c_uid = make_uid(DEMO_PROJECT_ID, "column", DEMO_PROVIDER, c_id)
        column_nodes.append({
            "uid": c_uid,
            "project_id": DEMO_PROJECT_ID,
            "name": c_name,
            "position": pos,
            "category": c_cat,
            "board_uid": board_uid,
        })
        col_board_rels.append({
            "source_uid": c_uid,
            "target_uid": board_uid,
            "properties": {},
        })
    writer.upsert_nodes(DEMO_PROJECT_ID, "Column", column_nodes)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Column", "NO_QUADRO", "Board", col_board_rels)

    # Módulos:
    # - api/payments (Diego ONLY -> BUS_FACTOR_1)
    # - api/auth (Ana, Bruno, Diego)
    # - api/core (Ana, Bruno, Diego)
    # - web/components (Carla, Elisa)
    # - web/pages (Carla, Elisa)
    # - infra/docker (Felipe)
    module_paths = [
        "api/payments",
        "api/auth",
        "api/core",
        "web/components",
        "web/pages",
        "infra/docker",
    ]
    module_nodes = []
    mod_repo_rels = []
    for m_path in module_paths:
        m_uid = make_uid(DEMO_PROJECT_ID, "module", DEMO_PROVIDER, m_path)
        module_nodes.append({
            "uid": m_uid,
            "project_id": DEMO_PROJECT_ID,
            "repo_full_name": "cognis-team/cognis-platform",
            "path": m_path,
        })
        mod_repo_rels.append({
            "source_uid": m_uid,
            "target_uid": repo_uid,
            "properties": {},
        })
    writer.upsert_nodes(DEMO_PROJECT_ID, "Module", module_nodes)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Module", "NO_REPOSITORIO", "Repo", mod_repo_rels)

    # ==========================================
    # 6. Commits e Alterações em Módulos
    # ==========================================
    # Plantado: Módulo api/payments só alterado por Diego (BUS_FACTOR_1)
    commit_nodes = []
    realizou_rels = []
    no_repo_rels = []
    alterou_rels = []

    def add_commit(sha: str, author_handle: str, authored_at: dt.datetime, module_path: str, adds: int, dels: int):
        c_uid = make_uid(DEMO_PROJECT_ID, "commit", DEMO_PROVIDER, sha)
        acc_uid = make_uid(DEMO_PROJECT_ID, "account", DEMO_PROVIDER, author_handle)
        mod_uid = make_uid(DEMO_PROJECT_ID, "module", DEMO_PROVIDER, module_path)

        commit_nodes.append({
            "uid": c_uid,
            "project_id": DEMO_PROJECT_ID,
            "sha": sha,
            "message": f"feat({module_path}): update code",
            "authored_at": authored_at,
            "additions": adds,
            "deletions": dels,
            "files_changed": 2,
            "url": f"https://demo.local/commits/{sha}",
        })
        realizou_rels.append({
            "source_uid": acc_uid,
            "target_uid": c_uid,
            "properties": {},
        })
        no_repo_rels.append({
            "source_uid": c_uid,
            "target_uid": repo_uid,
            "properties": {},
        })
        alterou_rels.append({
            "source_uid": c_uid,
            "target_uid": mod_uid,
            "properties": {"additions": adds, "deletions": dels},
        })

    # Diego altera api/payments (6 commits; 100% dos commits e alterações são de Diego)
    for i in range(1, 7):
        ts = dt.datetime(2026, 1, 10 + i, 14, 0, 0, tzinfo=dt.timezone.utc)
        add_commit(f"sha_pay_{i:02d}", "diego", ts, "api/payments", 45 + i * 5, 5 + i)

    # Backend: Ana, Bruno e Diego alteram api/auth e api/core
    for i in range(1, 4):
        ts = dt.datetime(2026, 1, 8 + i * 2, 11, 0, 0, tzinfo=dt.timezone.utc)
        add_commit(f"sha_auth_ana_{i:02d}", "ana", ts, "api/auth", 30, 4)
        add_commit(f"sha_auth_bruno_{i:02d}", "bruno", ts, "api/auth", 25, 6)
        add_commit(f"sha_auth_diego_{i:02d}", "diego", ts, "api/auth", 20, 2)
        add_commit(f"sha_core_ana_{i:02d}", "ana", ts, "api/core", 40, 10)
        add_commit(f"sha_core_bruno_{i:02d}", "bruno", ts, "api/core", 35, 8)

    # Frontend: Carla e Elisa alteram web/components e web/pages
    for i in range(1, 5):
        ts = dt.datetime(2026, 1, 9 + i * 2, 15, 0, 0, tzinfo=dt.timezone.utc)
        add_commit(f"sha_comp_carla_{i:02d}", "carla", ts, "web/components", 50, 12)
        add_commit(f"sha_comp_elisa_{i:02d}", "elisa", ts, "web/components", 45, 8)
        add_commit(f"sha_page_carla_{i:02d}", "carla", ts, "web/pages", 30, 5)
        add_commit(f"sha_page_elisa_{i:02d}", "elisa", ts, "web/pages", 35, 7)

    # Felipe altera infra/docker isoladamente (1 commit)
    add_commit("sha_infra_felipe_01", "felipe", dt.datetime(2026, 1, 15, 10, 0, 0, tzinfo=dt.timezone.utc), "infra/docker", 20, 5)

    writer.upsert_nodes(DEMO_PROJECT_ID, "Commit", commit_nodes)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Account", "REALIZOU", "Commit", realizou_rels)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Commit", "NO_REPOSITORIO", "Repo", no_repo_rels)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Commit", "ALTEROU", "Module", alterou_rels)

    # ==========================================
    # 7. Pull Requests e Reviews
    # ==========================================
    # Plantado:
    # 1. Bruno dá ~60% dos reviews (REVIEW_CONCENTRATION)
    # 2. Silos: Ana, Bruno, Diego (backend) <-> Carla, Elisa (frontend)
    # 3. Felipe tem <= 1 colaborador (ISOLATED_MEMBER)
    pr_nodes = []
    review_nodes = []
    abriu_rels = []
    pr_repo_rels = []
    enviou_rels = []
    sobre_rels = []

    pr_counter = 0
    rev_counter = 0

    def add_pr_and_reviews(
        author_handle: str,
        reviewer_handles: list[str],
        title: str,
        created_at: dt.datetime,
    ):
        nonlocal pr_counter, rev_counter
        pr_counter += 1
        p_num = pr_counter
        pr_uid = make_uid(DEMO_PROJECT_ID, "pr", DEMO_PROVIDER, str(p_num))
        author_acc = make_uid(DEMO_PROJECT_ID, "account", DEMO_PROVIDER, author_handle)

        first_rev_at = created_at + dt.timedelta(hours=2) if reviewer_handles else None

        pr_nodes.append({
            "uid": pr_uid,
            "project_id": DEMO_PROJECT_ID,
            "number": p_num,
            "title": title,
            "state": "merged",
            "created_at": created_at,
            "closed_at": created_at + dt.timedelta(days=1),
            "merged_at": created_at + dt.timedelta(days=1),
            "additions": 80,
            "deletions": 15,
            "changed_files": 3,
            "first_review_at": first_rev_at,
            "url": f"https://demo.local/pulls/{p_num}",
        })
        abriu_rels.append({
            "source_uid": author_acc,
            "target_uid": pr_uid,
            "properties": {},
        })
        pr_repo_rels.append({
            "source_uid": pr_uid,
            "target_uid": repo_uid,
            "properties": {},
        })

        for rev_handle in reviewer_handles:
            rev_counter += 1
            r_uid = make_uid(DEMO_PROJECT_ID, "review", DEMO_PROVIDER, str(rev_counter))
            rev_acc = make_uid(DEMO_PROJECT_ID, "account", DEMO_PROVIDER, rev_handle)
            rev_time = created_at + dt.timedelta(hours=2)

            review_nodes.append({
                "uid": r_uid,
                "project_id": DEMO_PROJECT_ID,
                "state": "APPROVED",
                "submitted_at": rev_time,
            })
            enviou_rels.append({
                "source_uid": rev_acc,
                "target_uid": r_uid,
                "properties": {},
            })
            sobre_rels.append({
                "source_uid": r_uid,
                "target_uid": pr_uid,
                "properties": {},
            })

    # Total de 20 reviews distribuídos:
    # Bruno: 12 reviews (12 / 20 = exatamente 60.0%)
    # Ana: 2 reviews
    # Diego: 2 reviews
    # Carla: 2 reviews
    # Elisa: 2 reviews
    # Backend PRs (Ana e Diego abrem, Bruno dá reviews principais):
    add_pr_and_reviews("ana", ["bruno"], "feat(auth): jwt tokens", dt.datetime(2026, 1, 10, 10, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("ana", ["bruno"], "fix(auth): expiry check", dt.datetime(2026, 1, 14, 10, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("ana", ["bruno", "diego"], "feat(core): service bus", dt.datetime(2026, 1, 18, 10, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("diego", ["bruno"], "feat(payments): pix gateway", dt.datetime(2026, 1, 12, 10, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("diego", ["bruno", "ana"], "feat(payments): webhook handler", dt.datetime(2026, 1, 16, 10, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("diego", ["bruno"], "fix(payments): currency round", dt.datetime(2026, 1, 22, 10, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("ana", ["bruno"], "feat(core): logging filter", dt.datetime(2026, 1, 25, 10, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("diego", ["bruno"], "feat(payments): refund api", dt.datetime(2026, 1, 28, 10, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("ana", ["bruno"], "refactor(auth): permissions", dt.datetime(2026, 2, 4, 10, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("diego", ["bruno", "ana"], "feat(payments): statement report", dt.datetime(2026, 2, 7, 10, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("ana", ["bruno"], "refactor(core): event bus dispatcher", dt.datetime(2026, 2, 8, 10, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("bruno", ["diego"], "refactor(core): bootstrap init", dt.datetime(2026, 2, 9, 10, 0, 0, tzinfo=dt.timezone.utc))

    # PR de Felipe (infra/docker): Bruno é o único revisor! (Felipe <= 1 colaborador)
    add_pr_and_reviews("felipe", ["bruno"], "chore(infra): update base dockerfile", dt.datetime(2026, 1, 20, 10, 0, 0, tzinfo=dt.timezone.utc))

    # Frontend PRs (Carla e Elisa entre si; sem arestas de review com backend):
    add_pr_and_reviews("carla", ["elisa"], "feat(ui): buttons and modals", dt.datetime(2026, 1, 15, 14, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("carla", ["elisa"], "feat(ui): header redesign", dt.datetime(2026, 1, 24, 14, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("elisa", ["carla"], "feat(pages): dashboard metrics", dt.datetime(2026, 1, 19, 14, 0, 0, tzinfo=dt.timezone.utc))
    add_pr_and_reviews("elisa", ["carla"], "feat(pages): profile settings", dt.datetime(2026, 2, 6, 14, 0, 0, tzinfo=dt.timezone.utc))

    # Review count check:
    # bruno: 10 + 1 (felipe) + 1 = 12 reviews
    # ana: 2 reviews
    # diego: 2 reviews
    # elisa: 2 reviews
    # carla: 2 reviews
    # total = 20 reviews. Bruno share = 12 / 20 = 0.60 (60%)!

    writer.upsert_nodes(DEMO_PROJECT_ID, "PullRequest", pr_nodes)
    writer.upsert_nodes(DEMO_PROJECT_ID, "Review", review_nodes)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Account", "ABRIU", "PullRequest", abriu_rels)
    writer.upsert_relationships(DEMO_PROJECT_ID, "PullRequest", "NO_REPOSITORIO", "Repo", pr_repo_rels)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Account", "ENVIOU", "Review", enviou_rels)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Review", "SOBRE", "PullRequest", sobre_rels)

    # ==========================================
    # 8. Tarefas (Tasks) e Padrão de Atraso em Sprint 3
    # ==========================================
    # Plantado: Sprint 3 com ~30% de tarefas atrasadas (LATE_RATE_HIGH)
    # Criaremos 10 tarefas concluídas na Sprint 3 com prazo:
    # - 7 tarefas pontuais: done_at <= due_at
    # - 3 tarefas atrasadas: done_at > due_at (exatamente 30%)
    task_nodes = []
    responsavel_rels = []
    na_coluna_rels = []
    no_quadro_rels = []

    done_col_uid = make_uid(DEMO_PROJECT_ID, "column", DEMO_PROVIDER, "demo-col-done")

    # Tarefas Sprint 1 e 2 (todas pontuais)
    for i in range(1, 7):
        t_id = f"task-s1-{i}"
        t_uid = make_uid(DEMO_PROJECT_ID, "task", DEMO_PROVIDER, t_id)
        assignee = "ana" if i % 2 == 0 else "diego"
        acc_uid = make_uid(DEMO_PROJECT_ID, "account", DEMO_PROVIDER, assignee)
        due = dt.datetime(2026, 1, 16, 18, 0, 0, tzinfo=dt.timezone.utc)
        done = dt.datetime(2026, 1, 15, 16, 0, 0, tzinfo=dt.timezone.utc)

        task_nodes.append({
            "uid": t_uid,
            "project_id": DEMO_PROJECT_ID,
            "kind": "card",
            "provider": DEMO_PROVIDER,
            "title": f"Tarefa Sprint 1 #{i}",
            "status_category": "done",
            "created_at": dt.datetime(2026, 1, 6, 9, 0, 0, tzinfo=dt.timezone.utc),
            "updated_at": done,
            "due_at": due,
            "done_at": done,
            "started_at": dt.datetime(2026, 1, 7, 9, 0, 0, tzinfo=dt.timezone.utc),
            "blocked": False,
            "labels": ["backend"],
            "transitions_json": None,
            "url": f"https://demo.local/cards/{t_id}",
        })
        responsavel_rels.append({
            "source_uid": acc_uid,
            "target_uid": t_uid,
            "properties": {},
        })
        na_coluna_rels.append({
            "source_uid": t_uid,
            "target_uid": done_col_uid,
            "properties": {},
        })
        no_quadro_rels.append({
            "source_uid": t_uid,
            "target_uid": board_uid,
            "properties": {},
        })

    # Tarefas Sprint 3: 10 tarefas concluídas dentro do período [2026-02-02, 2026-02-15]
    # Tarefas 1 a 7: pontuais (done_at <= due_at)
    # Tarefas 8 a 10: atrasadas (done_at > due_at) -> 3/10 = 30%!
    s3_assignees = ["ana", "diego", "bruno", "carla", "elisa", "ana", "carla", "diego", "elisa", "bruno"]
    for i in range(1, 11):
        t_id = f"task-s3-{i:02d}"
        t_uid = make_uid(DEMO_PROJECT_ID, "task", DEMO_PROVIDER, t_id)
        assignee = s3_assignees[i - 1]
        acc_uid = make_uid(DEMO_PROJECT_ID, "account", DEMO_PROVIDER, assignee)

        created = dt.datetime(2026, 2, 2, 9, 0, 0, tzinfo=dt.timezone.utc)
        started = dt.datetime(2026, 2, 3, 9, 0, 0, tzinfo=dt.timezone.utc)

        if i <= 7:
            # Pontual: prazo dia 10, concluído dia 9
            due = dt.datetime(2026, 2, 10, 18, 0, 0, tzinfo=dt.timezone.utc)
            done = dt.datetime(2026, 2, 9, 16, 0, 0, tzinfo=dt.timezone.utc)
        else:
            # Atrasada: prazo dia 7, concluído dia 12
            due = dt.datetime(2026, 2, 7, 18, 0, 0, tzinfo=dt.timezone.utc)
            done = dt.datetime(2026, 2, 12, 16, 0, 0, tzinfo=dt.timezone.utc)

        task_nodes.append({
            "uid": t_uid,
            "project_id": DEMO_PROJECT_ID,
            "kind": "card",
            "provider": DEMO_PROVIDER,
            "title": f"Tarefa Sprint 3 #{i}",
            "status_category": "done",
            "created_at": created,
            "updated_at": done,
            "due_at": due,
            "done_at": done,
            "started_at": started,
            "blocked": False,
            "labels": ["sprint3"],
            "transitions_json": None,
            "url": f"https://demo.local/cards/{t_id}",
        })
        responsavel_rels.append({
            "source_uid": acc_uid,
            "target_uid": t_uid,
            "properties": {},
        })
        na_coluna_rels.append({
            "source_uid": t_uid,
            "target_uid": done_col_uid,
            "properties": {},
        })
        no_quadro_rels.append({
            "source_uid": t_uid,
            "target_uid": board_uid,
            "properties": {},
        })

    writer.upsert_nodes(DEMO_PROJECT_ID, "Task", task_nodes)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Account", "RESPONSAVEL_POR", "Task", responsavel_rels)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Task", "NA_COLUNA", "Column", na_coluna_rels)
    writer.upsert_relationships(DEMO_PROJECT_ID, "Task", "NO_QUADRO", "Board", no_quadro_rels)

    stats = {
        "project_id": DEMO_PROJECT_ID,
        "people_count": len(people_data),
        "commit_count": len(commit_nodes),
        "pr_count": len(pr_nodes),
        "review_count": len(review_nodes),
        "task_count": len(task_nodes),
        "sprints_count": len(created_sprints),
        "bruno_reviews": 12,
        "total_reviews": len(review_nodes),
        "bruno_review_share": 12 / len(review_nodes),
        "sprint3_late_count": 3,
        "sprint3_total_tasks": 10,
        "sprint3_late_rate": 0.30,
    }
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Semear dados de demonstração do COGNIS (SPEC §15.2)")
    parser.add_argument("--user-email", default="demo@cognis.local", help="E-mail do usuário dono do projeto demo")
    parser.add_argument("--no-reset", action="store_true", help="Não limpar nós anteriores antes de semear")
    args = parser.parse_args()

    driver = create_neo4j_driver()
    with SessionLocal() as session:
        user = ensure_demo_user(session, email=args.user_email)
        stats = seed_demo(driver, session, user_id=user.id, reset=not args.no_reset)
        print("Dataset de demonstração gerado com sucesso:")
        for k, v in stats.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
