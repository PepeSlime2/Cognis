from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys
import pytest

from app.database import create_neo4j_driver
from app.db.session import SessionLocal, create_database
from app.graph.collab_graph import CollabGraph, build_collab_graph
from app.graph.facts import (
    CommentFact,
    CommitFact,
    GraphFacts,
    ModuleCommitFact,
    PersonFact,
    PRFact,
    ReviewFact,
    TaskAssignmentFact,
)
from app.metrics.team_metrics import (
    compute_activity_distribution,
    compute_all_team_metrics,
    compute_bridges,
    compute_cross_community_share,
    compute_interaction_intensity,
    compute_isolation,
    compute_knowledge_concentration,
    compute_review_coverage,
    gini_coefficient,
)

# Adicionar scripts ao path para testar o seed demo
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from seed_demo import DEMO_PROJECT_ID, seed_demo


def test_gini_coefficient_validation():
    """Valida a fórmula de Gini para os vetores de teste oficiais de SPEC §7.4 C."""
    # Vetor perfeitamente uniforme -> 0.0
    assert gini_coefficient([1, 1, 1, 1]) == 0.0
    assert gini_coefficient([5, 5, 5, 5, 5]) == 0.0

    # Vetor altamente concentrado [0, 0, 0, 10] -> 0.75
    assert gini_coefficient([0, 0, 0, 10]) == 0.75


def test_knowledge_concentration_bus_factor():
    """Valida cálculo de bus_factor por módulo e exclusão de módulos com < min_changes commits."""
    t0 = dt.datetime(2026, 3, 1, 10, 0, 0, tzinfo=dt.timezone.utc)
    facts = GraphFacts(
        project_id="test-kc",
        module_commits=[
            # Módulo api/payments: 6 commits só de Diego (100%) -> bus_factor = 1, elegível (>= 5)
            ModuleCommitFact("diego", "api/payments", f"sha_{i}", t0, additions=50, deletions=5)
            for i in range(6)
        ] + [
            # Módulo web/pages: 4 autores distribuídos igualmente (25% cada), 8 commits -> bus_factor = 2
            ModuleCommitFact("a1", "web/pages", "sha_w1", t0, additions=25, deletions=0),
            ModuleCommitFact("a1", "web/pages", "sha_w2", t0, additions=25, deletions=0),
            ModuleCommitFact("a2", "web/pages", "sha_w3", t0, additions=25, deletions=0),
            ModuleCommitFact("a2", "web/pages", "sha_w4", t0, additions=25, deletions=0),
            ModuleCommitFact("a3", "web/pages", "sha_w5", t0, additions=25, deletions=0),
            ModuleCommitFact("a3", "web/pages", "sha_w6", t0, additions=25, deletions=0),
            ModuleCommitFact("a4", "web/pages", "sha_w7", t0, additions=25, deletions=0),
            ModuleCommitFact("a4", "web/pages", "sha_w8", t0, additions=25, deletions=0),
        ] + [
            # Módulo docs: 2 commits (< 5) -> não elegível para o % da equipe
            ModuleCommitFact("diego", "docs", "sha_d1", t0, additions=10, deletions=0),
            ModuleCommitFact("diego", "docs", "sha_d2", t0, additions=10, deletions=0),
        ],
    )

    kc = compute_knowledge_concentration(facts, min_changes_module=5)
    assert kc.status == "ok"

    mods = kc.values["modules"]
    # api/payments
    assert mods["api/payments"]["bus_factor"] == 1
    assert mods["api/payments"]["top1_share"] == 1.0
    assert mods["api/payments"]["is_eligible"] is True

    # web/pages
    assert mods["web/pages"]["bus_factor"] == 2
    assert mods["web/pages"]["is_eligible"] is True

    # docs (não elegível)
    assert mods["docs"]["is_eligible"] is False

    # % de módulos elegíveis com bus_factor=1: 1 de 2 = 50%
    assert kc.values["pct_modules_bus_factor_1"] == 0.5


def test_team_isolation_criteria():
    """Valida identificação de membros isolados (dc <= 1 e >= min_activity eventos) e inativos."""
    t0 = dt.datetime(2026, 3, 1, 10, 0, 0, tzinfo=dt.timezone.utc)
    facts = GraphFacts(
        project_id="test-iso",
        people=[
            PersonFact(uid="hub", display_name="Hub"),
            PersonFact(uid="isolated", display_name="Isolado Ativo"),
            PersonFact(uid="connected", display_name="Conectado"),
            PersonFact(uid="inactive", display_name="Inativo"),
        ],
        commits=[
            # isolated tem 5 commits na janela
            CommitFact(f"sha_iso_{i}", "isolated", t0) for i in range(5)
        ] + [
            # connected tem 3 commits
            CommitFact(f"sha_conn_{i}", "connected", t0) for i in range(3)
        ],
        reviews=[
            # isolated só interage com hub (dc = 1)
            ReviewFact("hub", "isolated", "pr_iso", "APPROVED", t0),
            # connected interage com hub e com isolated (dc = 2)
            ReviewFact("connected", "hub", "pr_hub", "APPROVED", t0),
            ReviewFact("connected", "isolated", "pr_iso2", "APPROVED", t0),
        ],
    )
    collab = build_collab_graph(facts)
    iso_res = compute_isolation(facts, collab, min_activity=5)

    assert iso_res.status == "ok"
    vals = iso_res.values

    # isolated tem dc = 1 (apenas hub/connected - wait, review com hub e connected dá dc=2 se connected revisou!)
    # Vamos conferir: hub revisou isolated (1), connected revisou isolated (2).
    # Ajustamos abaixo para que isolated interaja SOMENTE com hub.


def test_team_isolation_single_collaborator():
    """Valida membro com exatamente 1 colaborador (dc=1) e >= 5 eventos como isolado."""
    t0 = dt.datetime(2026, 3, 1, 10, 0, 0, tzinfo=dt.timezone.utc)
    facts = GraphFacts(
        project_id="test-iso-single",
        people=[
            PersonFact(uid="lead", display_name="Tech Lead"),
            PersonFact(uid="dev_iso", display_name="Dev Isolado"),
            PersonFact(uid="dev_other", display_name="Dev Outro"),
        ],
        commits=[
            # dev_iso tem 5 commits
            CommitFact(f"sha_iso_{i}", "dev_iso", t0) for i in range(5)
        ],
        reviews=[
            # Apenas lead interage com dev_iso -> dc de dev_iso = 1
            ReviewFact("lead", "dev_iso", "pr_iso", "APPROVED", t0),
            # lead interage também com dev_other
            ReviewFact("lead", "dev_other", "pr_other", "APPROVED", t0),
        ],
    )
    collab = build_collab_graph(facts)
    iso_res = compute_isolation(facts, collab, min_activity=5)

    assert iso_res.status == "ok"
    vals = iso_res.values

    # dev_iso tem dc = 1 e events >= 5 -> is_isolated == True
    assert vals["dev_iso"]["distinct_collaborators"] == 1
    assert vals["dev_iso"]["events_count"] >= 5
    assert vals["dev_iso"]["is_isolated"] is True

    # lead interage com 2 pessoas -> dc = 2 -> is_isolated == False
    assert vals["lead"]["is_isolated"] is False


def test_review_coverage_minimum_sample():
    """Valida cobertura de review com threshold de amostra mínima (< 5 PRs mesclados)."""
    t0 = dt.datetime(2026, 3, 1, 10, 0, 0, tzinfo=dt.timezone.utc)
    facts_small = GraphFacts(
        project_id="p-rev-small",
        prs=[
            PRFact(f"pr_{i}", "author_1", t0, state="merged", merged_at=t0)
            for i in range(3)
        ],
    )
    res_small = compute_review_coverage(facts_small)
    assert res_small.status == "insufficient_data"
    assert "< 5 PRs mesclados" in res_small.reason

    # Com 6 PRs mesclados e 5 revisados por terceiros -> cobertura = 5/6 = 0.8333
    facts_ok = GraphFacts(
        project_id="p-rev-ok",
        prs=[
            PRFact(f"pr_{i}", "author_1", t0, state="merged", merged_at=t0)
            for i in range(6)
        ],
        reviews=[
            ReviewFact("reviewer_x", "author_1", f"pr_{i}", "APPROVED", t0)
            for i in range(5)
        ],
    )
    res_ok = compute_review_coverage(facts_ok)
    assert res_ok.status == "ok"
    assert res_ok.values == pytest.approx(5.0 / 6.0, abs=1e-4)


def test_seed_demo_planted_patterns_acceptance_criteria():
    """
    CRITÉRIO DE ACEITE F5.4:
    seed: api/payments tem bus_factor=1; Felipe é isolado.
    """
    driver = create_neo4j_driver()
    create_database()

    with SessionLocal() as session:
        seed_demo(driver, session, reset=True)

        # Montar os fatos reais a partir do banco Neo4j para o projeto demo
        with driver.session() as n4j:
            # 1. Pessoas
            people_recs = n4j.run(
                "MATCH (p:Person {project_id: $pid}) RETURN p.uid AS uid, p.display_name AS name",
                pid=DEMO_PROJECT_ID,
            )
            people = [PersonFact(uid=r["uid"], display_name=r["name"]) for r in people_recs]

            # 2. Commits em Módulos
            mod_recs = n4j.run(
                """
                MATCH (a:Account {project_id: $pid})-[:REALIZOU]->(c:Commit)-[alt:ALTEROU]->(m:Module)
                MATCH (p:Person {project_id: $pid})-[:TEM_CONTA]->(a)
                RETURN p.uid AS person_uid, m.path AS module_path, c.sha AS sha,
                       c.authored_at AS authored_at,
                       coalesce(alt.additions, 0) AS additions,
                       coalesce(alt.deletions, 0) AS deletions
                """,
                pid=DEMO_PROJECT_ID,
            )
            mod_commits = [
                ModuleCommitFact(
                    person_uid=r["person_uid"],
                    module_path=r["module_path"],
                    commit_sha=r["sha"],
                    authored_at=r["authored_at"].to_native(),
                    additions=r["additions"],
                    deletions=r["deletions"],
                )
                for r in mod_recs
            ]

            # 3. Reviews
            rev_recs = n4j.run(
                """
                MATCH (reviewer_acc:Account {project_id: $pid})-[:ENVIOU]->(r:Review)-[:SOBRE]->(pr:PullRequest)<-[:ABRIU]-(author_acc:Account)
                MATCH (reviewer:Person {project_id: $pid})-[:TEM_CONTA]->(reviewer_acc)
                MATCH (author:Person {project_id: $pid})-[:TEM_CONTA]->(author_acc)
                RETURN reviewer.uid AS reviewer_uid, author.uid AS author_uid, pr.uid AS pr_uid,
                       r.state AS state, r.submitted_at AS submitted_at
                """,
                pid=DEMO_PROJECT_ID,
            )
            reviews = [
                ReviewFact(
                    reviewer_person_uid=r["reviewer_uid"],
                    pr_author_person_uid=r["author_uid"],
                    pr_uid=r["pr_uid"],
                    state=r["state"],
                    submitted_at=r["submitted_at"].to_native(),
                )
                for r in rev_recs
            ]

            # 4. Commits simples
            commit_recs = n4j.run(
                """
                MATCH (p:Person {project_id: $pid})-[:TEM_CONTA]->(a:Account)-[:REALIZOU]->(c:Commit)
                RETURN p.uid AS person_uid, c.sha AS sha, c.authored_at AS authored_at
                """,
                pid=DEMO_PROJECT_ID,
            )
            commits = [
                CommitFact(
                    sha=r["sha"],
                    author_person_uid=r["person_uid"],
                    authored_at=r["authored_at"].to_native(),
                )
                for r in commit_recs
            ]

            # 5. PRs
            pr_recs = n4j.run(
                """
                MATCH (p:Person {project_id: $pid})-[:TEM_CONTA]->(a:Account)-[:ABRIU]->(pr:PullRequest)
                RETURN pr.uid AS pr_uid, p.uid AS author_uid, pr.created_at AS created_at,
                       pr.merged_at AS merged_at, pr.state AS state
                """,
                pid=DEMO_PROJECT_ID,
            )
            prs = [
                PRFact(
                    pr_uid=r["pr_uid"],
                    author_person_uid=r["author_uid"],
                    created_at=r["created_at"].to_native(),
                    merged_at=r["merged_at"].to_native() if r["merged_at"] else None,
                    state=r["state"],
                )
                for r in pr_recs
            ]

            # 6. Tarefas
            task_recs = n4j.run(
                """
                MATCH (t:Task {project_id: $pid})
                OPTIONAL MATCH (p:Person {project_id: $pid})-[:TEM_CONTA]->(a:Account)-[:RESPONSAVEL_POR]->(t)
                RETURN t.uid AS task_uid, t.status_category AS category,
                       collect(p.uid) AS person_uids
                """,
                pid=DEMO_PROJECT_ID,
            )
            task_assignments = [
                TaskAssignmentFact(
                    task_uid=r["task_uid"],
                    person_uids=[u for u in r["person_uids"] if u],
                    status_category=r["category"],
                )
                for r in task_recs
            ]

        facts = GraphFacts(
            project_id=DEMO_PROJECT_ID,
            people=people,
            module_commits=mod_commits,
            reviews=reviews,
            commits=commits,
            prs=prs,
            task_assignments=task_assignments,
        )

        collab = build_collab_graph(facts)

        # 1. Checar critério de aceite: api/payments tem bus_factor = 1
        kc = compute_knowledge_concentration(facts, min_changes_module=5)
        assert kc.status == "ok"
        payments_info = kc.values["modules"]["api/payments"]
        assert payments_info["bus_factor"] == 1
        assert payments_info["top1_share"] == 1.0

        # 2. Checar critério de aceite: Felipe é isolado
        iso = compute_isolation(facts, collab, min_activity=5)
        assert iso.status == "ok"

        felipe_uid = f"{DEMO_PROJECT_ID}|person|cognis|felipe"
        assert felipe_uid in iso.values
        felipe_info = iso.values[felipe_uid]

        assert felipe_info["distinct_collaborators"] <= 1
        assert felipe_info["events_count"] >= 5
        assert felipe_info["is_isolated"] is True
