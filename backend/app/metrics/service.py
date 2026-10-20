from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import MetricSnapshot, Project, SyncRun
from ..graph.collab_graph import CollabGraph, build_collab_graph
from ..graph.facts import GraphFacts, load_facts_from_neo4j
from ..metrics.flow_metrics import compute_all_flow_metrics
from ..metrics.graph_metrics import compute_all_graph_metrics
from ..metrics.person_metrics import compute_all_person_metrics
from ..metrics.team_metrics import compute_all_team_metrics
from ..metrics.windows import TimeWindow

DEFAULT_SETTINGS: dict[str, Any] = {
    "edge_weights": {
        "review": 1.0,
        "comment": 0.5,
        "shared_task": 1.0,
        "pr_closes_task": 0.5,
        "shared_module": 0.25,
    },
    "score_weights": {
        "participation": 0.25,
        "collaboration": 0.30,
        "delivery": 0.30,
        "quality": 0.15,
    },
    "thresholds": {
        "bus_factor_min_changes": 5,
        "review_concentration_pct": 0.50,
        "review_concentration_high_pct": 0.70,
        "review_concentration_min_reviews": 6,
        "pr_wait_high_h": 48.0,
        "pr_wait_critical_h": 96.0,
        "review_coverage_min": 0.80,
        "review_coverage_critical": 0.50,
        "isolation_min_activity": 5,
        "silos_modularity_min": 0.30,
        "silos_cross_community_max": 0.15,
        "task_concentration_gini": 0.45,
        "task_concentration_top1_pct": 0.40,
        "task_concentration_min_tasks": 8,
        "late_rate_high": 0.25,
        "late_rate_critical": 0.40,
        "completion_rate_low": 0.60,
        "completion_rate_critical": 0.40,
        "wip_limit": 4,
        "blocked_aging_days": 7.0,
        "stale_tasks_days": 14.0,
        "rework_high": 0.20,
        "collab_drop_pct": 0.30,
    },
    "min_edge_weight": 1.0,
    "wip_limit": 4,
    "module_depth": 2,
    "ignore_globs": ["*.lock", "package-lock.json", "node_modules/**"],
    "auto_sync": False,
    "sync_interval_min": 60,
}


def merge_settings(user_settings: dict[str, Any] | None) -> dict[str, Any]:
    """Combina as configurações do usuário com os valores padrão do SPEC."""
    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    if not user_settings:
        return merged

    for key, val in user_settings.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key].update(val)
        else:
            merged[key] = val
    return merged


def compute_config_hash(settings: dict[str, Any] | None) -> str:
    """
    Calcula sha256 canônico das configurações relevantes que impactam métricas (SPEC §7.5).
    Mudar pesos de arestas, scores ou limiares altera o config_hash.
    """
    effective = merge_settings(settings)
    relevant = {
        "edge_weights": effective.get("edge_weights"),
        "score_weights": effective.get("score_weights"),
        "thresholds": effective.get("thresholds"),
        "min_edge_weight": effective.get("min_edge_weight"),
        "wip_limit": effective.get("wip_limit"),
        "module_depth": effective.get("module_depth"),
        "ignore_globs": sorted(effective.get("ignore_globs", [])),
    }
    canonical = json.dumps(relevant, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_data_version(db: Session, project_id: str) -> str:
    """
    Retorna a versão dos dados da janela: o ID da última sincronização bem-sucedida (SPEC §7.5).
    Se nenhuma sincronização tiver ocorrido, retorna 'v0'.
    """
    stmt = (
        select(SyncRun)
        .where(SyncRun.project_id == project_id, SyncRun.status == "success")
        .order_by(SyncRun.finished_at.desc())
        .limit(1)
    )
    last_run = db.execute(stmt).scalar_one_or_none()
    if last_run is not None:
        return str(last_run.id)
    return "v0"


def get_metrics_bundle(
    db: Session,
    neo4j_driver: Any,
    project: Project,
    window: TimeWindow,
    force_refresh: bool = False,
    raw_facts: GraphFacts | None = None,
) -> dict[str, Any]:
    """
    Pipeline de cálculo e snapshot caching das métricas (SPEC §7.5).
    1. Calcula config_hash e data_version.
    2. Se existe metric_snapshots correspondente e não force_refresh -> devolve do cache.
    3. Senão -> calcula todas as métricas (A, B, C, D) -> persiste snapshot -> devolve.
    """
    effective_settings = merge_settings(project.settings_json)
    config_hash = compute_config_hash(effective_settings)
    data_version = get_data_version(db, project.id)

    # 1. Verificar cache
    if not force_refresh:
        stmt = select(MetricSnapshot).where(
            MetricSnapshot.project_id == project.id,
            MetricSnapshot.window_from == window.start_utc,
            MetricSnapshot.window_to == window.end_utc,
            MetricSnapshot.config_hash == config_hash,
            MetricSnapshot.data_version == data_version,
        )
        snapshot = db.execute(stmt).scalar_one_or_none()
        if snapshot is not None:
            cached_bundle = dict(snapshot.bundle_json)
            cached_bundle["cached"] = True
            return cached_bundle

    # 2. Carregar fatos e construir grafo
    if raw_facts is not None:
        facts = raw_facts
    else:
        facts = load_facts_from_neo4j(neo4j_driver, project.id, window=window)

    collab = build_collab_graph(facts, config=effective_settings)

    # 3. Calcular todos os catálogos
    graph_metrics = compute_all_graph_metrics(collab)
    person_metrics = compute_all_person_metrics(
        facts,
        collab,
        score_weights=effective_settings.get("score_weights"),
    )
    team_metrics = compute_all_team_metrics(facts, collab)
    flow_metrics = compute_all_flow_metrics(
        facts,
        window=window,
        wip_limit=int(effective_settings.get("wip_limit", 4)),
    )

    all_metrics = {
        **graph_metrics,
        **person_metrics,
        **team_metrics,
        **flow_metrics,
    }
    metrics_payload = {k: v.to_dict() for k, v in all_metrics.items()}

    bundle: dict[str, Any] = {
        "project_id": project.id,
        "window": window.to_dict(),
        "data_version": data_version,
        "config_hash": config_hash,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "warnings": [],
        "metrics": metrics_payload,
        "signals": [],  # Será populado na F6
        "cached": False,
    }

    # 4. Gravar snapshot
    existing_stmt = select(MetricSnapshot).where(
        MetricSnapshot.project_id == project.id,
        MetricSnapshot.window_from == window.start_utc,
        MetricSnapshot.window_to == window.end_utc,
        MetricSnapshot.config_hash == config_hash,
        MetricSnapshot.data_version == data_version,
    )
    existing_snapshot = db.execute(existing_stmt).scalar_one_or_none()
    if existing_snapshot is not None:
        existing_snapshot.bundle_json = bundle
    else:
        new_snapshot = MetricSnapshot(
            project_id=project.id,
            window_from=window.start_utc,
            window_to=window.end_utc,
            config_hash=config_hash,
            data_version=data_version,
            bundle_json=bundle,
        )
        db.add(new_snapshot)

    db.commit()
    return bundle
