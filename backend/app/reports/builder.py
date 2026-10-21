from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from ..llm.facts_builder import Anonymizer, sanitize_text
from ..llm.schemas import AnalysisSection
from ..metrics.registry import METRICS_CATALOG, MetricCatalogEntry
from .models import (
    CalloutBlock,
    ChartBlock,
    GraphImageBlock,
    KPIItem,
    KPIsBlock,
    ReportAppendix,
    ReportBlock,
    ReportMeta,
    ReportModel,
    ReportSection,
    TableBlock,
    TextBlock,
)

ReportType = Literal["sprint", "gerencial", "individual", "gargalos", "colaboracao"]


def _format_metric_val(metric_dict: dict[str, Any] | None, default_unit: str = "") -> str:
    if not metric_dict:
        return "—"
    status = metric_dict.get("status", "ok")
    if status == "insufficient_data":
        return "Dados insuficientes"
    if status == "not_applicable":
        return "N/A"

    val = metric_dict.get("values")
    if val is None:
        val = metric_dict.get("value")
    if val is None:
        return "—"

    unit = metric_dict.get("unit") or default_unit

    if isinstance(val, (int, float)):
        if unit in ("0-1", "%", "percent"):
            pct = val * 100 if unit == "0-1" and val <= 1.0 else val
            return f"{round(pct, 1)}%"
        if unit in ("days", "dias"):
            return f"{round(val, 1)} d"
        if unit in ("hours", "horas", "h"):
            return f"{round(val, 1)} h"
        return f"{round(val, 2)}"

    if isinstance(val, dict):
        if "median" in val and "p85" in val:
            med = val["median"]
            p85 = val["p85"]
            u_suffix = f" {unit}" if unit else ""
            if med is not None and p85 is not None:
                return f"med {round(med, 1)}{u_suffix} (p85: {round(p85, 1)}{u_suffix})"
        if "bus_factor" in val:
            return f"{val.get('bus_factor')}"
        if "gini" in val:
            return f"Gini: {round(val.get('gini', 0), 2)}"
        if "rate" in val:
            return f"{round(val['rate'] * 100, 1)}%"

    return str(val)


def _get_metric_item(bundle: dict[str, Any], metric_id: str) -> dict[str, Any] | None:
    return bundle.get("metrics", {}).get(metric_id)


def _build_definitions(used_metric_ids: set[str]) -> list[str]:
    catalog_map: dict[str, MetricCatalogEntry] = {e.id: e for e in METRICS_CATALOG}
    definitions: list[str] = []
    for m_id in sorted(used_metric_ids):
        if m_id in catalog_map:
            entry = catalog_map[m_id]
            definitions.append(f"{entry.name} ({entry.id}): {entry.description} [Fórmula: {entry.formula}]")
    return definitions


def build_report(
    project_id: str,
    project_name: str,
    bundle: dict[str, Any],
    report_type: ReportType,
    analysis_section: AnalysisSection | None = None,
    analysis_source: str | None = None,
    target_person_uid: str | None = None,
    target_person_name: str | None = None,
    anonymize: bool = False,
    graph_png_path: str | None = None,
) -> ReportModel:
    """
    Construtor oficial do ReportModel (SPEC §10.1, §10.2).
    Monta o modelo JSON unificado que serve de fonte única da verdade para renderizadores HTML, DOCX e PDF.
    """
    anonymizer = Anonymizer(enabled=anonymize)
    used_metric_ids: set[str] = set()

    def get_val(m_id: str, default_unit: str = "") -> str:
        used_metric_ids.add(m_id)
        return _format_metric_val(_get_metric_item(bundle, m_id), default_unit)

    window_data = bundle.get("window", {})
    window_label = window_data.get("label") or f"{window_data.get('from', '')} a {window_data.get('to', '')}"
    signals = bundle.get("signals", [])

    # Anonimização de pessoa alvo caso aplicável
    display_person_name = anonymizer.get_name(target_person_name) if target_person_name else None

    # Títulos e Metadados
    title_map = {
        "sprint": f"Relatório de Sprint — {window_label}",
        "gerencial": f"Relatório Gerencial de Colaboração — {project_name}",
        "individual": f"Perfil de Colaboração — {display_person_name or 'Colaborador'}",
        "gargalos": f"Diagnóstico de Gargalos e Riscos de Fluxo — {project_name}",
        "colaboracao": f"Análise da Rede de Colaboração — {project_name}",
    }
    report_title = title_map.get(report_type, f"Relatório {report_type.title()} — {project_name}")

    meta = ReportMeta(
        type=report_type,
        title=report_title,
        project=project_name,
        project_id=project_id,
        window=window_data,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        model="llama3.1:8b" if analysis_source == "ollama" else ("template" if analysis_source else None),
        data_version=bundle.get("data_version"),
        anonymized=anonymize,
        person_name=display_person_name,
    )

    sections: list[ReportSection] = []
    limitations: list[str] = [
        "Métricas calculadas exclusivamente com base nos eventos registrados na janela temporal.",
        "Indicadores de qualidade e retrabalho são proxies e devem ser interpretados no contexto do time.",
    ]

    # =========================================================================
    # 1. TIPO SPRINT
    # =========================================================================
    if report_type == "sprint":
        # KPIs da Sprint
        kpi_items = [
            KPIItem(label="Taxa de Conclusão", value=get_val("flow.completion_rate", "%"), hint="Itens concluídos sobre planejados"),
            KPIItem(label="Taxa de Atraso", value=get_val("flow.late_rate", "%"), hint="Itens com prazo estourado"),
            KPIItem(label="Lead Time (p50/p85)", value=get_val("flow.lead_time", "dias"), hint="Criação até conclusão"),
            KPIItem(label="Cycle Time (p50/p85)", value=get_val("flow.cycle_time", "dias"), hint="Início da execução até conclusão"),
        ]
        sections.append(ReportSection(id="kpis", title="Indicadores de Entrega e Fluxo", blocks=[KPIsBlock(items=kpi_items)]))

        # Eficiência de Revisões
        rev_kpis = [
            KPIItem(label="Tempo até 1º Review", value=get_val("flow.pr_time_to_first_review", "horas"), hint="Espera mediana"),
            KPIItem(label="Tempo até Merge", value=get_val("flow.pr_time_to_merge", "horas"), hint="Abertura até merge"),
            KPIItem(label="Taxa de Retrabalho", value=get_val("flow.rework", "%"), hint="PRs com alterações solicitadas"),
        ]
        sections.append(ReportSection(id="reviews", title="Dinâmica de Revisão de Código", blocks=[KPIsBlock(items=rev_kpis)]))

        # Signals detectados
        if signals:
            sig_rows = []
            for s in signals:
                subj = anonymizer.get_name(s.get("subject")) if s.get("subject") else "—"
                sig_rows.append([s.get("severity", "").upper(), s.get("code", ""), subj, sanitize_text(s.get("title", ""), 60)])
            sections.append(
                ReportSection(
                    id="signals",
                    title="Alertas e Signals Detectados na Sprint",
                    blocks=[
                        TableBlock(
                            title="Signals Ativos",
                            columns=["Severidade", "Código", "Sujeito", "Descrição"],
                            rows=sig_rows,
                        )
                    ],
                )
            )

        # Síntese IA / Regras
        if analysis_section:
            blocks: list[ReportBlock] = [
                TextBlock(
                    origin="llm" if analysis_source == "ollama" else "template",
                    markdown=f"### Resumo da Sprint\n\n{analysis_section.resumo}",
                )
            ]
            if analysis_section.achados:
                achados_md = "\n".join(f"- **{a.titulo}** ({a.severidade}): {a.descricao}" for a in analysis_section.achados)
                blocks.append(TextBlock(origin="data", markdown=f"### Achados Identificados\n\n{achados_md}"))
            if analysis_section.recomendacoes:
                recs_md = "\n".join(f"- **{r.acao}**: {r.justificativa}" for r in analysis_section.recomendacoes)
                blocks.append(TextBlock(origin="data", markdown=f"### Recomendações para a Próxima Sprint\n\n{recs_md}"))
            sections.append(ReportSection(id="analysis", title="Síntese da Dinâmica e Recomendações", blocks=blocks))

    # =========================================================================
    # 2. TIPO GERENCIAL
    # =========================================================================
    elif report_type == "gerencial":
        # KPIs Macro
        kpis = [
            KPIItem(label="Densidade da Rede", value=get_val("graph.density"), hint="Proporção de interações realizadas"),
            KPIItem(label="Modularidade", value=get_val("graph.modularity"), hint="Grau de divisão em silos"),
            KPIItem(label="Taxa de Conclusão", value=get_val("flow.completion_rate", "%"), hint="Média de entrega da equipe"),
            KPIItem(label="Taxa de Atraso", value=get_val("flow.late_rate", "%"), hint="Demandas em atraso"),
        ]
        sections.append(ReportSection(id="kpis", title="Visão Geral da Equipe", blocks=[KPIsBlock(items=kpis)]))

        # Distribuição de Atividades
        dist_kpis = [
            KPIItem(label="Distribuição de Tarefas", value=get_val("team.activity_distribution"), hint="Gini da alocação de cards"),
            KPIItem(label="Intensidade de Interação", value=get_val("team.interaction_intensity"), hint="Total de eventos colaborativos"),
            KPIItem(label="Compartilhamento Cross-Community", value=get_val("team.cross_community_share", "%"), hint="Interação entre frentes"),
        ]
        sections.append(ReportSection(id="distribution", title="Equilíbrio e Distribuição de Esforço", blocks=[KPIsBlock(items=dist_kpis)]))

        # Imagem do Grafo
        if graph_png_path:
            sections.append(
                ReportSection(
                    id="graph",
                    title="Topologia da Rede de Colaboração",
                    blocks=[GraphImageBlock(png_path=graph_png_path, caption="Grafo de colaboração da equipe colorido por comunidade")],
                )
            )

        # Riscos e Alertas
        high_signals = [s for s in signals if s.get("severity") in ("high", "medium")]
        if high_signals:
            sig_rows = [
                [s.get("severity", "").upper(), s.get("code", ""), anonymizer.get_name(s.get("subject")) or "Equipe", s.get("title", "")]
                for s in high_signals
            ]
            sections.append(
                ReportSection(
                    id="risks",
                    title="Riscos Prioritários",
                    blocks=[
                        TableBlock(columns=["Severidade", "Código", "Foco", "Alerta"], rows=sig_rows),
                        CalloutBlock(level="warning", text="Recomenda-se priorizar o nivelamento das cargas de trabalho apontadas nos alertas de alta severidade."),
                    ],
                )
            )

        # Síntese Executiva
        if analysis_section:
            blocks = [
                TextBlock(origin="llm" if analysis_source == "ollama" else "template", markdown=f"### Síntese Executiva\n\n{analysis_section.resumo}")
            ]
            if analysis_section.recomendacoes:
                recs_md = "\n".join(f"1. **{r.acao}**: {r.justificativa}" for r in analysis_section.recomendacoes)
                blocks.append(TextBlock(origin="data", markdown=f"### Ações Recomendadas\n\n{recs_md}"))
            sections.append(ReportSection(id="synthesis", title="Diagnóstico e Recomendações Estratégicas", blocks=blocks))

    # =========================================================================
    # 3. TIPO INDIVIDUAL (SPEC §10.1, §13.4)
    # =========================================================================
    elif report_type == "individual":
        target_keys = {k for k in (target_person_uid, target_person_name) if k}
        target_raw = target_person_name or target_person_uid or "Colaborador"
        p_name = anonymizer.get_name(target_raw)

        # 1. Diretrizes de Uso e Ética (SPEC §13.4 e Lei de Goodhart)
        ethical_callouts: list[ReportBlock] = [
            CalloutBlock(
                level="info",
                text="Uso Responsável: Este perfil descreve padrões de colaboração e processo no contexto da equipe, sem constituir avaliação de desempenho ou mérito individual (Lei de Goodhart). Não deve ser utilizado como ranking ou avaliação funcional.",
            ),
            CalloutBlock(
                level="warning",
                text="Aviso sobre Indicadores Proxy: O indicador person.quality é um proxy indireto baseado na frequência de solicitações de alteração em revisões de PR e retrabalho, condicionado a amostragem mínima (>= 3). Não reflete habilidade técnica ou competência individual.",
            ),
        ]
        sections.append(ReportSection(id="ethical_notice", title="Diretrizes de Uso Responsável", blocks=ethical_callouts))

        # Função auxiliar para extrair valor e média da equipe
        def _get_metric_stats(metric_id: str) -> tuple[str, str]:
            item = _get_metric_item(bundle, metric_id)
            if not item:
                return "—", "—"
            vals = item.get("values")
            user_val_str = "—"
            team_avg_str = "—"
            if isinstance(vals, dict):
                # Valor da pessoa
                for k in target_keys:
                    if k in vals and vals[k] is not None:
                        try:
                            user_val_str = f"{round(float(vals[k]), 1)}"
                        except Exception:
                            user_val_str = str(vals[k])
                        break
                # Média da equipe
                num_vals = [float(v) for v in vals.values() if isinstance(v, (int, float))]
                if num_vals:
                    team_avg_str = f"{round(sum(num_vals) / len(num_vals), 1)}"
            return user_val_str, team_avg_str

        # Componentes usados no score geral
        overall_item = _get_metric_item(bundle, "person.overall")
        used_comps: list[str] = []
        if overall_item and isinstance(overall_item.get("inputs"), dict):
            used_map = overall_item["inputs"].get("used_components", {})
            for k in target_keys:
                if k in used_map and isinstance(used_map[k], list):
                    used_comps = used_map[k]
                    break

        comp_trans = {
            "participation": "Participação",
            "collaboration": "Colaboração",
            "delivery": "Entrega",
            "quality": "Qualidade",
        }
        used_label = ", ".join(comp_trans.get(c, c) for c in used_comps) if used_comps else "Componentes disponíveis"

        overall_val, overall_avg = _get_metric_stats("person.overall")
        part_val, part_avg = _get_metric_stats("person.participation")
        collab_val, collab_avg = _get_metric_stats("person.collaboration")
        delivery_val, delivery_avg = _get_metric_stats("person.delivery")
        quality_val, quality_avg = _get_metric_stats("person.quality")

        kpis = [
            KPIItem(label="Índice Geral", value=overall_val, hint=f"Composto de: {used_label} (Média equipe: {overall_avg})"),
            KPIItem(label="Participação", value=part_val, hint=f"Volume de atividades (Média equipe: {part_avg})"),
            KPIItem(label="Colaboração", value=collab_val, hint=f"Centralidade na rede (Média equipe: {collab_avg})"),
            KPIItem(label="Entrega", value=delivery_val, hint=f"Tarefas concluídas vs planejadas (Média equipe: {delivery_avg})"),
            KPIItem(label="Proxy de Qualidade", value=quality_val, hint=f"Proxy de retrabalho inverso (Média equipe: {quality_avg})"),
        ]
        sections.append(ReportSection(id="indices", title=f"Índices de Contribuição de {p_name}", blocks=[KPIsBlock(items=kpis)]))

        # Contadores brutos (person.counters)
        counters_item = _get_metric_item(bundle, "person.counters")
        person_counters_dict: dict[str, Any] = {}
        if counters_item and isinstance(counters_item.get("values"), dict):
            c_vals = counters_item["values"]
            for k in target_keys:
                if k in c_vals and isinstance(c_vals[k], dict):
                    person_counters_dict = c_vals[k]
                    break

        if person_counters_dict:
            counter_rows = [
                ["Commits Realizados", str(person_counters_dict.get("commits", 0))],
                ["Pull Requests Abertos", str(person_counters_dict.get("prs_opened", 0))],
                ["Pull Requests Mesclados", str(person_counters_dict.get("prs_merged", 0))],
                ["Revisões Realizadas (Dadas)", str(person_counters_dict.get("reviews_given", 0))],
                ["Revisões Recebidas", str(person_counters_dict.get("reviews_received", 0))],
                ["Comentários em PRs e Tarefas", str(person_counters_dict.get("comments", 0))],
                ["Tarefas Atribuídas", str(person_counters_dict.get("tasks_assigned", 0))],
                ["Tarefas Concluídas", str(person_counters_dict.get("tasks_done", 0))],
                ["Colaboradores Distintos Interagidos", str(person_counters_dict.get("distinct_collaborators", 0))],
            ]
            sections.append(
                ReportSection(
                    id="counters",
                    title="Volume de Atividades no Período",
                    blocks=[
                        TableBlock(columns=["Tipo de Atividade", "Quantidade Registrada"], rows=counter_rows)
                    ],
                )
            )

        # Principais Parceiros (team.interaction_intensity -> pairs)
        intensity_item = _get_metric_item(bundle, "team.interaction_intensity")
        collab_partners: list[tuple[str, float]] = []
        if intensity_item and isinstance(intensity_item.get("values"), dict):
            pairs_dict = intensity_item["values"].get("pairs", {})
            if isinstance(pairs_dict, dict):
                for pair_key, weight in pairs_dict.items():
                    if "<->" in pair_key:
                        p1, p2 = pair_key.split("<->", 1)
                        if p1 in target_keys:
                            collab_partners.append((p2, float(weight)))
                        elif p2 in target_keys:
                            collab_partners.append((p1, float(weight)))

        collab_partners.sort(key=lambda x: x[1], reverse=True)
        if collab_partners:
            partner_rows = [
                [anonymizer.get_name(partner), f"{round(w, 2)}"]
                for partner, w in collab_partners[:6]
            ]
            sections.append(
                ReportSection(
                    id="network",
                    title="Principais Parceiros de Colaboração",
                    blocks=[
                        TableBlock(columns=["Colaborador Parceiro", "Intensidade da Interação"], rows=partner_rows)
                    ],
                )
            )

        # Módulos de Atuação (team.knowledge_concentration -> by_module)
        kc_item = _get_metric_item(bundle, "team.knowledge_concentration")
        modules_rows: list[list[str]] = []
        if kc_item and isinstance(kc_item.get("values"), dict):
            by_mod = kc_item["values"].get("by_module", {})
            if isinstance(by_mod, dict):
                for mod_name, mod_info in by_mod.items():
                    if isinstance(mod_info, dict):
                        top_author = mod_info.get("top1_author")
                        if top_author in target_keys:
                            share_str = f"{round(mod_info.get('top1_share', 0) * 100, 1)}%"
                            bf_str = str(mod_info.get("bus_factor", "—"))
                            modules_rows.append([mod_name, share_str, bf_str])

        if modules_rows:
            sections.append(
                ReportSection(
                    id="modules",
                    title="Módulos de Atuação Principal",
                    blocks=[
                        TableBlock(columns=["Módulo / Diretório", "Concentração de Commits", "Fator Ônibus"], rows=modules_rows),
                        CalloutBlock(level="info", text="Módulos onde o colaborador é o principal autor de commits registrado na janela."),
                    ],
                )
            )

        # Atividades e WIP
        wip_val, wip_avg = _get_metric_stats("flow.wip_per_person")
        wip_text = f"Tarefas ativas simultâneas (WIP): {wip_val} (Média da equipe: {wip_avg})."
        act_blocks: list[ReportBlock] = [
            CalloutBlock(level="info", text=wip_text)
        ]
        sections.append(ReportSection(id="activity", title="Fluxo e Carga de Trabalho Atual", blocks=act_blocks))

        if analysis_section:
            sections.append(
                ReportSection(
                    id="analysis",
                    title="Comentários sobre a Dinâmica de Trabalho",
                    blocks=[
                        TextBlock(
                            origin="llm" if analysis_source == "ollama" else "template",
                            markdown=f"### Síntese da Atuação\n\n{analysis_section.resumo}"
                        )
                    ],
                )
            )

    # =========================================================================
    # 4. TIPO GARGALOS
    # =========================================================================
    elif report_type == "gargalos":
        kpis = [
            KPIItem(label="Tempo até 1º Review", value=get_val("flow.pr_time_to_first_review", "horas"), hint="Espera antes do feedback"),
            KPIItem(label="Tempo até Merge", value=get_val("flow.pr_time_to_merge", "horas"), hint="Ciclo completo de PR"),
            KPIItem(label="Taxa de Retrabalho", value=get_val("flow.rework", "%"), hint="PRs com revisões extras"),
            KPIItem(label="Fator Ônibus", value=get_val("team.knowledge_concentration"), hint="Menor redundância por módulo"),
        ]
        sections.append(ReportSection(id="kpis", title="Indicadores de Fluxo e Bloqueio", blocks=[KPIsBlock(items=kpis)]))

        # Concentração e Fator Ônibus
        kc_item = _get_metric_item(bundle, "team.knowledge_concentration")
        kc_val = kc_item.get("values") if kc_item else {}
        kc_rows = []
        if isinstance(kc_val, dict):
            by_module = kc_val.get("by_module", {})
            for mod, data in by_module.items():
                if isinstance(data, dict):
                    author = anonymizer.get_name(data.get("top1_author")) if data.get("top1_author") else "—"
                    share = f"{round(data.get('top1_share', 0) * 100, 1)}%"
                    bf = str(data.get("bus_factor", 1))
                    kc_rows.append([mod, bf, author, share])

        if kc_rows:
            sections.append(
                ReportSection(
                    id="knowledge",
                    title="Concentração de Conhecimento por Módulo",
                    blocks=[
                        TableBlock(columns=["Módulo", "Fator Ônibus", "Principal Autor", "Concentração"], rows=kc_rows),
                        CalloutBlock(level="warning", text="Módulos com fator ônibus = 1 possuem risco operacional de retenção exclusiva de conhecimento."),
                    ],
                )
            )

        # Dependências Críticas e Signals
        crit_signals = [s for s in signals if "BUS_FACTOR" in s.get("code", "") or "REVIEW_CONCENTRATION" in s.get("code", "") or "LATE" in s.get("code", "")]
        if crit_signals:
            sig_rows = [
                [s.get("severity", "").upper(), s.get("code", ""), anonymizer.get_name(s.get("subject")) or "Equipe", s.get("title", "")]
                for s in crit_signals
            ]
            sections.append(
                ReportSection(
                    id="critical_signals",
                    title="Pontos de Atenção Imediata",
                    blocks=[TableBlock(columns=["Severidade", "Código", "Foco", "Alerta"], rows=sig_rows)],
                )
            )

        if analysis_section:
            sections.append(
                ReportSection(
                    id="synthesis",
                    title="Recomendações para Desobstrução do Fluxo",
                    blocks=[
                        TextBlock(origin="data", markdown=f"### Análise de Bloqueios\n\n{analysis_section.resumo}"),
                        TextBlock(origin="data", markdown="\n".join(f"- **{r.acao}**: {r.justificativa}" for r in analysis_section.recomendacoes)),
                    ],
                )
            )

    # =========================================================================
    # 5. TIPO COLABORAÇÃO
    # =========================================================================
    elif report_type == "colaboracao":
        kpis = [
            KPIItem(label="Densidade da Rede", value=get_val("graph.density"), hint="Conectividade geral"),
            KPIItem(label="Modularidade", value=get_val("graph.modularity"), hint="Separação em subgrupos"),
            KPIItem(label="Compartilhamento Cross-Community", value=get_val("team.cross_community_share", "%"), hint="Troca entre comunidades"),
            KPIItem(label="Intensidade Total", value=get_val("team.interaction_intensity"), hint="Volume de conexões"),
        ]
        sections.append(ReportSection(id="kpis", title="Topologia e Densidade Social", blocks=[KPIsBlock(items=kpis)]))

        # Imagem do Grafo
        if graph_png_path:
            sections.append(
                ReportSection(
                    id="graph",
                    title="Mapa da Rede de Colaboradores",
                    blocks=[GraphImageBlock(png_path=graph_png_path, caption="Visualização das comunidades e elos de colaboração")],
                )
            )

        # Isolamento e Pontes
        iso_m = _get_metric_item(bundle, "team.isolation")
        bridges_m = _get_metric_item(bundle, "team.bridges")
        struct_rows = []
        if iso_m and isinstance(iso_m.get("values"), dict):
            isolated = iso_m["values"].get("isolated_members", [])
            for m in isolated:
                struct_rows.append(["Isolado", anonymizer.get_name(m), "Grau de colaboração com a equipe muito reduzido"])
        if bridges_m and isinstance(bridges_m.get("values"), dict):
            bridges = bridges_m["values"].get("bridge_members", [])
            for b in bridges:
                struct_rows.append(["Ponte", anonymizer.get_name(b), "Atua como elo de comunicação entre diferentes comunidades"])

        if struct_rows:
            sections.append(
                ReportSection(
                    id="structures",
                    title="Papéis Estruturais na Rede",
                    blocks=[TableBlock(columns=["Papel", "Colaborador", "Descrição"], rows=struct_rows)],
                )
            )

        if analysis_section:
            sections.append(
                ReportSection(
                    id="analysis",
                    title="Diagnóstico de Colaboração e Integração",
                    blocks=[
                        TextBlock(origin="data", markdown=f"### Síntese da Rede\n\n{analysis_section.resumo}"),
                        TextBlock(origin="data", markdown="\n".join(f"- **{r.acao}**: {r.justificativa}" for r in analysis_section.recomendacoes)),
                    ],
                )
            )

    # Anexo oficial com definições e conformidade ética (SPEC §10.2, §13.4)
    appendix = ReportAppendix(
        definitions=_build_definitions(used_metric_ids),
        limitations=limitations,
    )

    return ReportModel(
        meta=meta,
        sections=sections,
        appendix=appendix,
    )
