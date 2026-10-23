from __future__ import annotations

import datetime as dt
from typing import Any, Literal
from zoneinfo import ZoneInfo

from neo4j import Driver
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Project, Sprint
from ..graph.collab_graph import build_collab_graph
from ..graph.facts import load_facts_from_neo4j
from .graph_metrics import (
    compute_centralization,
    compute_community,
    compute_components,
    compute_density,
    compute_modularity,
)
from .windows import TimeWindow, parse_window, window_from_sprint


def compute_team_evolution(
    driver: Driver,
    db: Session,
    project: Project,
    granularity: Literal["sprint", "14d"] = "sprint",
    min_edge_weight: float = 1.0,
    until_utc: dt.datetime | None = None,
) -> dict[str, Any]:
    """
    team.evolution: série histórica por período (sprint ou 14 dias) (SPEC §7.4 C, §11).
    Calcula para cada período:
    - graph.density
    - graph.modularity
    - graph.centralization
    - número de componentes (components_count)
    - pessoas ativas (active_people_count)
    - reviews_per_pr
    - weight_per_person (intensidade média por pessoa ativa)
    - deltas em relação ao período anterior (incluindo density_drop_pct para COLLAB_DROP).
    Retorna status='insufficient_data' se houver menos de 2 períodos com dados.
    """
    tz_str = project.timezone or "America/Sao_Paulo"

    periods_windows: list[tuple[str, TimeWindow]] = []

    if granularity == "sprint":
        query = select(Sprint).where(Sprint.project_id == project.id)
        if until_utc is not None:
            query = query.where(Sprint.end_date <= until_utc)
        sprints = list(db.scalars(query.order_by(Sprint.start_date.asc())).all())

        if len(sprints) < 2:
            return {
                "id": "team.evolution",
                "scope": "team",
                "status": "insufficient_data",
                "unit": "série",
                "values": {
                    "granularity": "sprint",
                    "periods": [],
                    "delta": None,
                },
                "reason": "Menos de 2 períodos com dados (necessário ao menos 2 sprints cadastradas)",
            }

        for s in sprints:
            w = window_from_sprint(s, timezone=tz_str)
            periods_windows.append((s.name, w))
    else:
        # Granularidade 14d: se houver sprints cadastradas, usa o horizonte delas
        # caso contrário, retroage a partir de hoje em 4 períodos de 14 dias
        query = select(Sprint).where(Sprint.project_id == project.id)
        if until_utc is not None:
            query = query.where(Sprint.end_date <= until_utc)
        sprints = list(db.scalars(query.order_by(Sprint.start_date.asc())).all())

        if sprints:
            first_w = window_from_sprint(sprints[0], timezone=tz_str)
            cur_start = first_w.start_utc.astimezone(ZoneInfo(tz_str)).date()
            for idx in range(1, len(sprints) + 1):
                cur_end = cur_start + dt.timedelta(days=13)
                w = parse_window(cur_start.isoformat(), cur_end.isoformat(), timezone=tz_str)
                periods_windows.append((f"Período {idx} (14d)", w))
                cur_start = cur_end + dt.timedelta(days=1)
        else:
            today = dt.datetime.now(ZoneInfo(tz_str)).date()
            # 4 períodos consecutivos de 14 dias retroagindo até hoje
            start_date = today - dt.timedelta(days=56)
            cur_start = start_date
            for idx in range(1, 5):
                cur_end = cur_start + dt.timedelta(days=13)
                w = parse_window(cur_start.isoformat(), cur_end.isoformat(), timezone=tz_str)
                periods_windows.append((f"Período {idx} (14d)", w))
                cur_start = cur_end + dt.timedelta(days=1)

    if len(periods_windows) < 2:
        return {
            "id": "team.evolution",
            "scope": "team",
            "status": "insufficient_data",
            "unit": "série",
            "values": {
                "granularity": granularity,
                "periods": [],
                "delta": None,
            },
            "reason": "Menos de 2 períodos com dados",
        }

    # Calcular métricas para cada período
    computed_periods: list[dict[str, Any]] = []

    for label, window in periods_windows:
        facts = load_facts_from_neo4j(driver, project.id, window)
        collab = build_collab_graph(facts, config={"min_edge_weight": min_edge_weight})

        density_res = compute_density(collab)
        density_val = density_res.values if density_res.status == "ok" and isinstance(density_res.values, (int, float)) else 0.0

        mod_res = compute_modularity(collab)
        mod_val = mod_res.values if mod_res.status == "ok" and isinstance(mod_res.values, (int, float)) else 0.0

        cent_res = compute_centralization(collab)
        cent_val = cent_res.values if cent_res.status == "ok" and isinstance(cent_res.values, (int, float)) else 0.0

        comp_res = compute_components(collab)
        components_count = (
            comp_res.values.get("count", 0)
            if comp_res.status == "ok" and isinstance(comp_res.values, dict)
            else 0
        )

        n_active = len(collab.active_nodes)
        n_prs = len(facts.prs)
        n_reviews = len(facts.reviews)
        reviews_per_pr = round(n_reviews / max(1, n_prs), 2) if n_prs > 0 else 0.0

        # Soma total dos pesos das arestas de colaboração dividida pelas pessoas ativas
        total_edge_weight = sum(data.get("weight", 0.0) for _, _, data in collab.G_u.edges(data=True))
        weight_per_person = round(total_edge_weight / max(1, n_active), 2) if n_active > 0 else 0.0

        period_data: dict[str, Any] = {
            "label": label,
            "from": str(window.start_date),
            "to": str(window.end_date),
            "density": float(density_val),
            "modularity": float(mod_val),
            "centralization": float(cent_val),
            "components_count": int(components_count),
            "active_people_count": int(n_active),
            "reviews_per_pr": float(reviews_per_pr),
            "weight_per_person": float(weight_per_person),
            "delta": None,
        }
        computed_periods.append(period_data)

    # Calcular deltas sequenciais
    for i in range(1, len(computed_periods)):
        prev = computed_periods[i - 1]
        curr = computed_periods[i]

        prev_w = float(prev["weight_per_person"])
        curr_w = float(curr["weight_per_person"])
        drop_pct = (prev_w - curr_w) / prev_w if prev_w > 0 else 0.0

        delta_info = {
            "density_drop_pct": round(max(0.0, drop_pct), 4),
            "prev_weight_per_person": round(prev_w, 2),
            "curr_weight_per_person": round(curr_w, 2),
            "delta_density": round(curr["density"] - prev["density"], 4),
            "delta_modularity": round(curr["modularity"] - prev["modularity"], 4),
            "delta_centralization": round(curr["centralization"] - prev["centralization"], 4),
            "delta_active_people": curr["active_people_count"] - prev["active_people_count"],
        }
        curr["delta"] = delta_info

    last_delta = computed_periods[-1].get("delta")

    return {
        "id": "team.evolution",
        "scope": "team",
        "status": "ok",
        "unit": "série",
        "values": {
            "granularity": granularity,
            "periods": computed_periods,
            "delta": last_delta,
        },
    }
