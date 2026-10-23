"""
Motor determinístico de detecção de Signals (SPEC §8).
Regras estritamente em Python determinístico com limiares configuráveis.
O LLM NUNCA calcula nem detecta signals; apenas interpreta os signals aqui gerados.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime as dt
from typing import Any, Literal

from ..graph.collab_graph import CollabGraph
from ..graph.facts import GraphFacts
from ..llm.templates import render_signal_message, render_signal_title
from .windows import TimeWindow


@dataclass
class SignalEvidence:
    metric_id: str
    value: Any
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SignalSubject:
    type: Literal["person", "module", "team"]
    id: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Signal:
    id: str
    code: str
    severity: Literal["info", "medium", "high"]
    title: str
    message: str
    subject: SignalSubject
    evidence: list[SignalEvidence]
    window: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "subject": self.subject.to_dict(),
            "evidence": [e.to_dict() for e in self.evidence],
            "window": self.window,
        }


def _get_metric_val(metrics: dict[str, Any], metric_id: str) -> Any:
    """Extrai values de um MetricResult ou dict de métrica."""
    m = metrics.get(metric_id)
    if not m:
        return None
    if isinstance(m, dict):
        if m.get("status") == "ok":
            return m.get("values")
        return None
    if hasattr(m, "status") and getattr(m, "status") == "ok":
        return getattr(m, "values", None)
    return None


def detect_signals(
    metrics: dict[str, Any],
    facts: GraphFacts | None = None,
    collab: CollabGraph | None = None,
    window: TimeWindow | None = None,
    settings: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> list[Signal]:
    """
    Executa o catálogo de 15 regras determinísticas de Signals (SPEC §8).
    Retorna lista ordenada de Signals detectados com ids S1, S2, etc.
    """
    thresholds = {}
    if settings:
        thresholds = settings.get("thresholds", {}) or {}

    win_dict = window.to_dict() if window is not None else {}
    current_time = now or (window.end_utc if window is not None else dt.datetime.now(dt.timezone.utc))

    # Mapear display names de pessoas
    person_names: dict[str, str] = {}
    if facts and facts.people:
        for p in facts.people:
            person_names[p.uid] = p.display_name

    detected: list[Signal] = []
    sig_counter = 0

    def next_id() -> str:
        nonlocal sig_counter
        sig_counter += 1
        return f"S{sig_counter}"

    # =========================================================================
    # 1. BUS_FACTOR_1: Módulo com bus_factor=1, >= 5 commits (min_changes_module)
    # Severity: high se módulo tem >= 20% das alterações do projeto, senão medium.
    # =========================================================================
    kc_vals = _get_metric_val(metrics, "team.knowledge_concentration")
    if kc_vals and isinstance(kc_vals, dict):
        modules = kc_vals.get("modules") if "modules" in kc_vals else kc_vals
        total_project_changes = sum(
            m.get("total_changes", 0) for m in modules.values() if isinstance(m, dict)
        )

        for mod_path, mod_data in modules.items():
            if not isinstance(mod_data, dict):
                continue
            if mod_data.get("is_eligible") and mod_data.get("bus_factor") == 1:
                top1_share = mod_data.get("top1_share", 1.0)
                mod_changes = mod_data.get("total_changes", 0)
                changes_share = (
                    mod_changes / float(total_project_changes)
                    if total_project_changes > 0
                    else 0.0
                )
                severity: Literal["medium", "high"] = "high" if changes_share >= 0.20 else "medium"

                # Tentar achar o autor principal nos commits de fatos
                author_display = "o autor principal"
                if facts:
                    author_changes: dict[str, int] = {}
                    for mc in facts.module_commits:
                        if mc.module_path == mod_path:
                            author_changes[mc.person_uid] = (
                                author_changes.get(mc.person_uid, 0)
                                + mc.additions
                                + mc.deletions
                            )
                    if author_changes:
                        top_author_uid = max(author_changes.items(), key=lambda kv: kv[1])[0]
                        author_display = person_names.get(top_author_uid, top_author_uid.split("|")[-1])

                code = "BUS_FACTOR_1"
                ctx = {
                    "module": mod_path,
                    "author": author_display,
                    "top1_share": top1_share,
                }
                detected.append(
                    Signal(
                        id=next_id(),
                        code=code,
                        severity=severity,
                        title=render_signal_title(code),
                        message=render_signal_message(code, ctx),
                        subject=SignalSubject(type="module", id=mod_path, label=mod_path),
                        evidence=[
                            SignalEvidence(
                                metric_id="team.knowledge_concentration",
                                value=f"bus_factor=1, top1={top1_share:.0%}, projeto={changes_share:.0%}",
                                unit="ratio",
                            )
                        ],
                        window=win_dict,
                    )
                )

    # =========================================================================
    # 2. REVIEW_CONCENTRATION: Uma pessoa dá >= 50% dos reviews (total >= 6)
    # Severity: high se >= 70%, senão medium.
    # =========================================================================
    rev_min = thresholds.get("review_concentration_min_reviews", 6)
    rev_pct_thresh = thresholds.get("review_concentration_pct", 0.50)
    rev_high_thresh = thresholds.get("review_concentration_high_pct", 0.70)

    # Coletar contagem de reviews por pessoa
    if facts:
        total_revs = len(facts.reviews)
        if total_revs >= rev_min:
            rev_counts: dict[str, int] = {}
            for r in facts.reviews:
                rev_counts[r.reviewer_person_uid] = rev_counts.get(r.reviewer_person_uid, 0) + 1

            for p_uid, count in rev_counts.items():
                share = count / float(total_revs)
                if share >= rev_pct_thresh:
                    severity = "high" if share >= rev_high_thresh else "medium"
                    name = person_names.get(p_uid, p_uid.split("|")[-1])
                    code = "REVIEW_CONCENTRATION"
                    ctx = {
                        "person": name,
                        "pct": share,
                        "n": count,
                        "total": total_revs,
                    }
                    detected.append(
                        Signal(
                            id=next_id(),
                            code=code,
                            severity=severity,
                            title=render_signal_title(code),
                            message=render_signal_message(code, ctx),
                            subject=SignalSubject(type="person", id=p_uid, label=name),
                            evidence=[
                                SignalEvidence(
                                    metric_id="flow.bottleneck_risk",
                                    value=f"{share:.0%} dos reviews ({count} de {total_revs})",
                                    unit="%",
                                )
                            ],
                            window=win_dict,
                        )
                    )

    # =========================================================================
    # 3. PR_WAIT_HIGH: p85 de pr_time_to_first_review > 48 h
    # Severity: high se > 96 h, senão medium.
    # =========================================================================
    pr_wait_high_h = thresholds.get("pr_wait_high_h", 48.0)
    pr_wait_crit_h = thresholds.get("pr_wait_critical_h", 96.0)
    pr_wait_vals = _get_metric_val(metrics, "flow.pr_time_to_first_review")
    if pr_wait_vals and pr_wait_vals.get("p85_h") is not None:
        p85_h = pr_wait_vals["p85_h"]
        if p85_h > pr_wait_high_h:
            severity = "high" if p85_h > pr_wait_crit_h else "medium"
            code = "PR_WAIT_HIGH"
            ctx = {"p85_h": p85_h, "threshold_h": pr_wait_high_h}
            detected.append(
                Signal(
                    id=next_id(),
                    code=code,
                    severity=severity,
                    title=render_signal_title(code),
                    message=render_signal_message(code, ctx),
                    subject=SignalSubject(type="team", id="team", label="Equipe"),
                    evidence=[
                        SignalEvidence(
                            metric_id="flow.pr_time_to_first_review",
                            value=p85_h,
                            unit="h",
                        )
                    ],
                    window=win_dict,
                )
            )

    # =========================================================================
    # 4. NO_REVIEW_MERGES: review_coverage < 0.80
    # Severity: high se < 0.50, senão medium.
    # =========================================================================
    rev_cov_min = thresholds.get("review_coverage_min", 0.80)
    rev_cov_crit = thresholds.get("review_coverage_critical", 0.50)
    rev_cov_vals = _get_metric_val(metrics, "team.review_coverage")
    cov: float | None = None
    if isinstance(rev_cov_vals, (int, float)):
        cov = float(rev_cov_vals)
    elif isinstance(rev_cov_vals, dict):
        cov = rev_cov_vals.get("review_coverage")

    if cov is not None and cov < rev_cov_min:
        severity = "high" if cov < rev_cov_crit else "medium"
        code = "NO_REVIEW_MERGES"
        ctx = {"coverage_pct": cov, "threshold_pct": rev_cov_min}
        detected.append(
            Signal(
                id=next_id(),
                code=code,
                severity=severity,
                title=render_signal_title(code),
                message=render_signal_message(code, ctx),
                subject=SignalSubject(type="team", id="team", label="Equipe"),
                evidence=[
                    SignalEvidence(
                        metric_id="team.review_coverage",
                        value=cov,
                        unit="ratio",
                    )
                ],
                window=win_dict,
            )
        )

    # =========================================================================
    # 5. ISOLATED_MEMBER: team.isolation.flag == True
    # Severity: medium
    # =========================================================================
    iso_vals = _get_metric_val(metrics, "team.isolation")
    if iso_vals:
        for p_uid, p_iso in iso_vals.items():
            if isinstance(p_iso, dict) and p_iso.get("is_isolated") is True:
                name = person_names.get(p_uid, p_uid.split("|")[-1])
                code = "ISOLATED_MEMBER"
                ctx = {
                    "person": name,
                    "events": p_iso.get("events_count", 0),
                    "collaborators": p_iso.get("distinct_collaborators", 0),
                }
                detected.append(
                    Signal(
                        id=next_id(),
                        code=code,
                        severity="medium",
                        title=render_signal_title(code),
                        message=render_signal_message(code, ctx),
                        subject=SignalSubject(type="person", id=p_uid, label=name),
                        evidence=[
                            SignalEvidence(
                                metric_id="team.isolation",
                                value=f"colaboradores={p_iso.get('distinct_collaborators')}, eventos={p_iso.get('events_count')}",
                                unit="",
                            )
                        ],
                        window=win_dict,
                    )
                )

    # =========================================================================
    # 6. SILOS: >= 2 comunidades, modularity >= 0.30 e cross_community_share < 0.15
    # Severity: medium
    # =========================================================================
    mod_thresh = thresholds.get("silos_modularity_min", 0.30)
    cross_thresh = thresholds.get("silos_cross_community_max", 0.15)
    comm_vals = _get_metric_val(metrics, "graph.community")
    mod_vals = _get_metric_val(metrics, "graph.modularity")
    cross_vals = _get_metric_val(metrics, "team.cross_community_share")

    n_communities = 0
    if comm_vals:
        n_communities = len(set(comm_vals.values())) if isinstance(comm_vals, dict) else 0

    if n_communities >= 2 and mod_vals is not None and cross_vals is not None:
        modularity = mod_vals if isinstance(mod_vals, (int, float)) else mod_vals.get("modularity", 0.0)
        cross_share = (
            cross_vals
            if isinstance(cross_vals, (int, float))
            else cross_vals.get("cross_community_share", 1.0)
        )
        if modularity >= mod_thresh and cross_share < cross_thresh:
            code = "SILOS"
            ctx = {
                "modularity": modularity,
                "cross_share": cross_share * 100.0,
            }
            detected.append(
                Signal(
                    id=next_id(),
                    code=code,
                    severity="medium",
                    title=render_signal_title(code),
                    message=render_signal_message(code, ctx),
                    subject=SignalSubject(type="team", id="team", label="Equipe"),
                    evidence=[
                        SignalEvidence(metric_id="graph.modularity", value=modularity, unit=""),
                        SignalEvidence(
                            metric_id="team.cross_community_share",
                            value=cross_share,
                            unit="ratio",
                        ),
                    ],
                    window=win_dict,
                )
            )

    # =========================================================================
    # 7. TASK_CONCENTRATION: Gini >= 0.45 OU pessoa com >= 40% das tarefas (total >= 8)
    # Severity: medium
    # =========================================================================
    gini_thresh = thresholds.get("task_concentration_gini", 0.45)
    top1_task_thresh = thresholds.get("task_concentration_top1_pct", 0.40)
    min_tasks_conc = thresholds.get("task_concentration_min_tasks", 8)

    act_vals = _get_metric_val(metrics, "team.activity_distribution")
    gini_tasks = act_vals.get("gini_tasks_assigned") if act_vals else None

    # Avaliar concentração por pessoa
    triggered_by_person = False
    if facts and facts.task_assignments:
        task_counts: dict[str, int] = {}
        for t in facts.task_assignments:
            for p_uid in t.person_uids:
                task_counts[p_uid] = task_counts.get(p_uid, 0) + 1

        total_assigned = sum(task_counts.values())
        if total_assigned >= min_tasks_conc and task_counts:
            top_uid, top_count = max(task_counts.items(), key=lambda kv: kv[1])
            share = top_count / float(total_assigned)
            if share >= top1_task_thresh:
                triggered_by_person = True
                name = person_names.get(top_uid, top_uid.split("|")[-1])
                code = "TASK_CONCENTRATION"
                ctx = {
                    "gini": gini_tasks or 0.0,
                    "top_info": f", com {name} concentrando {share:.0%} das tarefas ({top_count} de {total_assigned})",
                }
                detected.append(
                    Signal(
                        id=next_id(),
                        code=code,
                        severity="medium",
                        title=render_signal_title(code),
                        message=render_signal_message(code, ctx),
                        subject=SignalSubject(type="person", id=top_uid, label=name),
                        evidence=[
                            SignalEvidence(
                                metric_id="team.activity_distribution",
                                value=f"{share:.0%} das tarefas ({top_count} de {total_assigned})",
                                unit="%",
                            )
                        ],
                        window=win_dict,
                    )
                )

    if not triggered_by_person and gini_tasks is not None and gini_tasks >= gini_thresh:
        code = "TASK_CONCENTRATION"
        ctx = {"gini": gini_tasks, "top_info": ""}
        detected.append(
            Signal(
                id=next_id(),
                code=code,
                severity="medium",
                title=render_signal_title(code),
                message=render_signal_message(code, ctx),
                subject=SignalSubject(type="team", id="team", label="Equipe"),
                evidence=[
                    SignalEvidence(
                        metric_id="team.activity_distribution",
                        value=gini_tasks,
                        unit="Gini",
                    )
                ],
                window=win_dict,
            )
        )

    # =========================================================================
    # 8. LATE_RATE_HIGH: late_rate >= 0.25
    # Severity: high se >= 0.40, senão medium.
    # =========================================================================
    late_high_thresh = thresholds.get("late_rate_high", 0.25)
    late_crit_thresh = thresholds.get("late_rate_critical", 0.40)
    late_vals = _get_metric_val(metrics, "flow.late_rate")
    if late_vals and late_vals.get("late_rate") is not None:
        lr = late_vals["late_rate"]
        if lr >= late_high_thresh:
            severity = "high" if lr >= late_crit_thresh else "medium"
            code = "LATE_RATE_HIGH"
            overdue_open = late_vals.get("overdue_open", 0)
            overdue_str = f" Há {overdue_open} tarefa(s) abertas com prazo vencido." if overdue_open > 0 else ""
            ctx = {
                "late_pct": lr,
                "late_count": late_vals.get("late_concluded_count", late_vals.get("late_count", 0)),
                "total_tasks": late_vals.get(
                    "total_concluded_with_due",
                    late_vals.get("total_with_due", late_vals.get("concluded_with_due_count", 0)),
                ),
                "overdue_info": overdue_str,
            }
            detected.append(
                Signal(
                    id=next_id(),
                    code=code,
                    severity=severity,
                    title=render_signal_title(code),
                    message=render_signal_message(code, ctx),
                    subject=SignalSubject(type="team", id="team", label="Equipe"),
                    evidence=[
                        SignalEvidence(
                            metric_id="flow.late_rate",
                            value=lr,
                            unit="ratio",
                        )
                    ],
                    window=win_dict,
                )
            )

    # =========================================================================
    # 9. LOW_COMPLETION: completion_rate < 0.60
    # Severity: high se < 0.40, senão medium.
    # =========================================================================
    comp_low_thresh = thresholds.get("completion_rate_low", 0.60)
    comp_crit_thresh = thresholds.get("completion_rate_critical", 0.40)
    comp_vals = _get_metric_val(metrics, "flow.completion_rate")
    if comp_vals and comp_vals.get("overall") is not None:
        cr = comp_vals["overall"]
        if cr < comp_low_thresh:
            severity = "high" if cr < comp_crit_thresh else "medium"
            code = "LOW_COMPLETION"
            ctx = {
                "completion_pct": cr,
                "done_count": comp_vals.get("done_count", 0),
                "planned_count": comp_vals.get("planned_count", 0),
            }
            detected.append(
                Signal(
                    id=next_id(),
                    code=code,
                    severity=severity,
                    title=render_signal_title(code),
                    message=render_signal_message(code, ctx),
                    subject=SignalSubject(type="team", id="team", label="Equipe"),
                    evidence=[
                        SignalEvidence(
                            metric_id="flow.completion_rate",
                            value=cr,
                            unit="ratio",
                        )
                    ],
                    window=win_dict,
                )
            )

    # =========================================================================
    # 10. WIP_HIGH: pessoa com wip > wip_limit
    # Severity: medium
    # =========================================================================
    wip_limit = int(settings.get("wip_limit", thresholds.get("wip_limit", 4)) if settings else 4)
    wip_vals = _get_metric_val(metrics, "flow.wip_per_person")
    if wip_vals and isinstance(wip_vals, dict):
        for p_uid, person_wip in wip_vals.items():
            if person_wip > wip_limit:
                name = person_names.get(p_uid, p_uid.split("|")[-1])
                code = "WIP_HIGH"
                ctx = {
                    "person": name,
                    "wip": person_wip,
                    "wip_limit": wip_limit,
                }
                detected.append(
                    Signal(
                        id=next_id(),
                        code=code,
                        severity="medium",
                        title=render_signal_title(code),
                        message=render_signal_message(code, ctx),
                        subject=SignalSubject(type="person", id=p_uid, label=name),
                        evidence=[
                            SignalEvidence(
                                metric_id="flow.wip_per_person",
                                value=person_wip,
                                unit="tasks",
                            )
                        ],
                        window=win_dict,
                    )
                )

    # =========================================================================
    # 11. BLOCKED_AGING: >= 2 tarefas bloqueadas há > 7 dias
    # Severity: medium
    # =========================================================================
    blocked_days_thresh = thresholds.get("blocked_aging_days", 7.0)
    if facts and facts.task_assignments:
        aging_blocked = 0
        oldest_age = 0.0
        for t in facts.task_assignments:
            if t.blocked and t.status_category != "done":
                ref_dt = t.blocked_since or t.created_at
                if ref_dt is not None:
                    age_d = max(0.0, (current_time - ref_dt).total_seconds() / 86400.0)
                    if age_d > oldest_age:
                        oldest_age = age_d
                    if age_d > blocked_days_thresh:
                        aging_blocked += 1

        if aging_blocked >= 2:
            code = "BLOCKED_AGING"
            ctx = {
                "count": aging_blocked,
                "days": blocked_days_thresh,
                "max_age_days": oldest_age,
            }
            detected.append(
                Signal(
                    id=next_id(),
                    code=code,
                    severity="medium",
                    title=render_signal_title(code),
                    message=render_signal_message(code, ctx),
                    subject=SignalSubject(type="team", id="team", label="Equipe"),
                    evidence=[
                        SignalEvidence(
                            metric_id="flow.critical_dependencies",
                            value=f"{aging_blocked} tarefas bloqueadas",
                            unit="tasks",
                        )
                    ],
                    window=win_dict,
                )
            )

    # =========================================================================
    # 12. STALE_TASKS: >= 3 tarefas em 'doing' sem atividade há > 14 dias
    # Severity: medium
    # =========================================================================
    stale_days_thresh = thresholds.get("stale_tasks_days", 14.0)
    if facts and facts.task_assignments:
        stale_count = 0
        for t in facts.task_assignments:
            if t.status_category == "doing":
                ref_dt = t.updated_at or t.started_at or t.created_at
                if ref_dt is not None:
                    age_d = max(0.0, (current_time - ref_dt).total_seconds() / 86400.0)
                    if age_d > stale_days_thresh:
                        stale_count += 1

        if stale_count >= 3:
            code = "STALE_TASKS"
            ctx = {"count": stale_count, "days": stale_days_thresh}
            detected.append(
                Signal(
                    id=next_id(),
                    code=code,
                    severity="medium",
                    title=render_signal_title(code),
                    message=render_signal_message(code, ctx),
                    subject=SignalSubject(type="team", id="team", label="Equipe"),
                    evidence=[
                        SignalEvidence(
                            metric_id="flow.cycle_time",
                            value=f"{stale_count} tarefas paradas em doing",
                            unit="tasks",
                        )
                    ],
                    window=win_dict,
                )
            )

    # =========================================================================
    # 13. REWORK_HIGH: rework >= 0.20
    # Severity: medium
    # =========================================================================
    rework_thresh = thresholds.get("rework_high", 0.20)
    rework_vals = _get_metric_val(metrics, "flow.rework")
    if rework_vals and rework_vals.get("rework_rate") is not None:
        rw = rework_vals["rework_rate"]
        if rw >= rework_thresh:
            code = "REWORK_HIGH"
            ctx = {
                "rework_pct": rw,
                "rework_count": rework_vals.get("rework_tasks_count", 0),
            }
            detected.append(
                Signal(
                    id=next_id(),
                    code=code,
                    severity="medium",
                    title=render_signal_title(code),
                    message=render_signal_message(code, ctx),
                    subject=SignalSubject(type="team", id="team", label="Equipe"),
                    evidence=[
                        SignalEvidence(
                            metric_id="flow.rework",
                            value=rw,
                            unit="ratio",
                        )
                    ],
                    window=win_dict,
                )
            )

    # =========================================================================
    # 14. COLLAB_DROP: team.evolution caiu >= 30% vs. período anterior
    # Severity: medium
    # =========================================================================
    collab_drop_thresh = thresholds.get("collab_drop_pct", 0.30)
    evo_vals = _get_metric_val(metrics, "team.evolution")
    if evo_vals and isinstance(evo_vals, dict) and evo_vals.get("delta"):
        delta = evo_vals["delta"]
        drop_pct = delta.get("density_drop_pct", 0.0)
        if drop_pct >= collab_drop_thresh:
            code = "COLLAB_DROP"
            ctx = {
                "drop_pct": drop_pct,
                "prev_intensity": delta.get("prev_weight_per_person", 0.0),
                "curr_intensity": delta.get("curr_weight_per_person", 0.0),
            }
            detected.append(
                Signal(
                    id=next_id(),
                    code=code,
                    severity="medium",
                    title=render_signal_title(code),
                    message=render_signal_message(code, ctx),
                    subject=SignalSubject(type="team", id="team", label="Equipe"),
                    evidence=[
                        SignalEvidence(
                            metric_id="team.evolution",
                            value=f"-{drop_pct:.0%}",
                            unit="%",
                        )
                    ],
                    window=win_dict,
                )
            )

    # =========================================================================
    # 15. INSUFFICIENT_DATA: métrica-chave com status insuficiente
    # Severity: info
    # =========================================================================
    # Só aciona se houver erro de mapeamento ou dados essenciais ausentes em métricas-chave
    insufficient_metrics = []
    for k, v in metrics.items():
        st = getattr(v, "status", None) or (v.get("status") if isinstance(v, dict) else None)
        if st == "insufficient_data":
            # Verificar se é métrica relevante como colunas não confirmadas
            reason = getattr(v, "reason", None) or (v.get("reason") if isinstance(v, dict) else "")
            if "colunas" in str(reason).lower() or "não confirmad" in str(reason).lower():
                insufficient_metrics.append((k, reason))

    if insufficient_metrics:
        code = "INSUFFICIENT_DATA"
        metric_names = ", ".join(m[0] for m in insufficient_metrics)
        primary_reason = insufficient_metrics[0][1]
        ctx = {"metrics": metric_names, "reason": primary_reason}
        detected.append(
            Signal(
                id=next_id(),
                code=code,
                severity="info",
                title=render_signal_title(code),
                message=render_signal_message(code, ctx),
                subject=SignalSubject(type="team", id="team", label="Equipe"),
                evidence=[
                    SignalEvidence(
                        metric_id=insufficient_metrics[0][0],
                        value=primary_reason,
                        unit="",
                    )
                ],
                window=win_dict,
            )
        )

    return detected
