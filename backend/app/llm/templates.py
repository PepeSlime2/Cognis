"""
Módulo de templates em PT-BR para signals determinísticos e relatórios (SPEC §8 e §9.3).
Usado como:
(a) Geração determinística de mensagens e títulos dos Signals;
(b) Fallback para análises sem IA (F7.4);
(c) Exemplos no prompt do LLM.
"""

from __future__ import annotations

from typing import Any


SIGNAL_TEMPLATES: dict[str, dict[str, str]] = {
    "BUS_FACTOR_1": {
        "title": "Fator de risco de conhecimento crítico (Bus Factor 1)",
        "message": (
            "O módulo '{module}' depende exclusivamente de {author} "
            "({top1_share:.0%} das alterações na janela). Se esta pessoa estiver indisponível, "
            "a equipe enfrentará gargalos críticos para manter ou evoluir este módulo."
        ),
    },
    "REVIEW_CONCENTRATION": {
        "title": "Concentração excessiva de revisões de código",
        "message": (
            "{person} concentra {pct:.0%} dos reviews do período ({n} de {total}). "
            "Isso cria dependência operacional e risco elevado de fila de espera para aprovação de PRs."
        ),
    },
    "PR_WAIT_HIGH": {
        "title": "Tempo elevado de espera para primeira revisão",
        "message": (
            "O percentil 85 do tempo até o primeiro review é de {p85_h:.1f} horas "
            "(limiar recomendado: {threshold_h:.1f} h). Pull requests demoram para receber "
            "feedback inicial, retardando o ciclo de entrega."
        ),
    },
    "NO_REVIEW_MERGES": {
        "title": "Baixa cobertura de revisão por pares em PRs mesclados",
        "message": (
            "Apenas {coverage_pct:.0%} dos pull requests foram mesclados com revisão por pares "
            "(limiar mínimo: {threshold_pct:.0%}). Alterações estão chegando à branch principal "
            "sem validação independente de outros membros."
        ),
    },
    "ISOLATED_MEMBER": {
        "title": "Colaborador isolado na rede de colaboração",
        "message": (
            "{person} possui atividade relevante ({events} eventos no período), mas interagiu com "
            "apenas {collaborators} colaborador(es). Risco de desalinhamento técnico e falta de apoio da equipe."
        ),
    },
    "SILOS": {
        "title": "Silos de comunicação entre grupos",
        "message": (
            "A equipe apresenta divisão em comunidades estanques (modularidade {modularity:.2f}) "
            "com apenas {cross_share:.1f}% das interações ocorrendo entre diferentes grupos. "
            "Risco de duplicação de esforço e falta de integração entre frentes."
        ),
    },
    "TASK_CONCENTRATION": {
        "title": "Desbalanceamento na distribuição de tarefas",
        "message": (
            "A atribuição de tarefas está desbalanceada na equipe (Gini={gini:.2f}{top_info}). "
            "Isso pode sobrecarregar membros-chave e subutilizar a capacidade de outros."
        ),
    },
    "LATE_RATE_HIGH": {
        "title": "Taxa elevada de tarefas entregues com atraso",
        "message": (
            "{late_pct:.0%} das tarefas concluídas com prazo foram entregues com atraso "
            "({late_count} de {total_tasks} tarefas).{overdue_info}"
        ),
    },
    "LOW_COMPLETION": {
        "title": "Baixa taxa de conclusão de tarefas planejadas",
        "message": (
            "Apenas {completion_pct:.0%} das tarefas planejadas para o período foram concluídas "
            "({done_count} de {planned_count} tarefas entregues)."
        ),
    },
    "WIP_HIGH": {
        "title": "Limite de trabalho em andamento (WIP) excedido",
        "message": (
            "{person} está com {wip} tarefas simultâneas em andamento/revisão "
            "(limite sugerido: {wip_limit}). Risco de fragmentação de atenção e entrega lenta."
        ),
    },
    "BLOCKED_AGING": {
        "title": "Tarefas bloqueadas há muito tempo",
        "message": (
            "{count} tarefas estão marcadas como bloqueadas há mais de {days:.0f} dias "
            "(tarefa mais antiga bloqueada há {max_age_days:.1f} dias)."
        ),
    },
    "STALE_TASKS": {
        "title": "Tarefas paradas em andamento sem movimentação",
        "message": (
            "{count} tarefas permanecem na coluna de em andamento ('doing') sem qualquer atividade "
            "recente há mais de {days:.0f} dias."
        ),
    },
    "REWORK_HIGH": {
        "title": "Índice elevado de retrabalho",
        "message": (
            "A taxa de retrabalho observada é de {rework_pct:.0%} ({rework_count} tarefas "
            "retornaram para fases anteriores de desenvolvimento). Pode indicar requisitos ambíguos "
            "ou problemas na validação inicial."
        ),
    },
    "COLLAB_DROP": {
        "title": "Queda na intensidade de colaboração",
        "message": (
            "A densidade de colaboração por pessoa ativa recuou {drop_pct:.0%} em relação "
            "ao período anterior ({prev_intensity:.2f} → {curr_intensity:.2f})."
        ),
    },
    "INSUFFICIENT_DATA": {
        "title": "Dados insuficientes para análise completa",
        "message": (
            "Alguns indicadores ({metrics}) não puderam ser calculados com confiabilidade "
            "por falta de registros suficientes na janela ({reason})."
        ),
    },
}


def render_signal_title(code: str) -> str:
    """Retorna o título oficial em PT-BR para o código do signal."""
    meta = SIGNAL_TEMPLATES.get(code)
    if meta and "title" in meta:
        return meta["title"]
    return f"Sinal de atenção: {code}"


def render_signal_message(code: str, context: dict[str, Any]) -> str:
    """Renderiza a mensagem do signal em PT-BR a partir do contexto fornecido."""
    meta = SIGNAL_TEMPLATES.get(code)
    if not meta or "message" not in meta:
        return f"Sinal detectado: {code}"

    try:
        return meta["message"].format(**context)
    except Exception:
        # Fallback resiliente caso falte alguma chave no context
        return meta["message"]


def generate_template_analysis(facts: dict[str, Any], scope: str = "team") -> AnalysisSection:
    """
    Gera uma AnalysisSection determinística por templates (SPEC §9.3 e §9.7).
    Usada como fallback quando o Ollama estiver indisponível ou reprovado no validador.
    """
    from .schemas import AnalysisSection, Evidence, Finding, Recommendation

    window = facts.get("window", {})
    team = facts.get("team", {})
    signals = facts.get("signals", [])
    metrics = facts.get("metrics", [])
    limits = facts.get("limits", [])

    w_from = window.get("from", "")
    w_to = window.get("to", "")
    active = team.get("active_members", 0)
    compl = team.get("completion_rate")
    
    compl_text = ""
    if isinstance(compl, (int, float)):
        if compl <= 1.0:
            compl_text = f" com taxa de conclusão de {round(compl * 100):.0f}%"
        else:
            compl_text = f" com taxa de conclusão de {round(compl):.0f}%"

    resumo = (
        f"Análise determinística baseada em regras para o escopo {scope} no período de {w_from} a {w_to}. "
        f"A equipe conta com {active} membros ativos{compl_text}."
    )
    if len(resumo) > 600:
        resumo = resumo[:599]

    # Achados baseados em signals
    achados: list[Finding] = []
    sev_map = {"high": "alta", "medium": "media", "low": "baixa", "info": "baixa"}
    for sig in signals[:5]:
        s_id = sig.get("id", "")
        code = sig.get("code", "")
        sev = sev_map.get(sig.get("severity", "info"), "baixa")
        subj = sig.get("subject")
        subj_str = f" envolvendo {subj}" if subj else ""
        title = render_signal_title(code)
        desc = f"Identificado o padrão de {title.lower()}{subj_str} registrado na evidência {s_id}."
        achados.append(
            Finding(
                titulo=title[:100],
                descricao=desc,
                severidade=sev,  # type: ignore
                evidencias=[Evidence(ref=s_id)],
            )
        )

    if not achados and metrics:
        m = metrics[0]
        m_id = m.get("id", "M1")
        achados.append(
            Finding(
                titulo="Indicador monitorado no período",
                descricao=f"Métrica {m.get('metric_id')} observada no valor {m.get('value')}.",
                severidade="baixa",
                evidencias=[Evidence(ref=m_id)],
            )
        )
    elif not achados:
        achados.append(
            Finding(
                titulo="Operação estável sem sinais críticos",
                descricao="Não foram detectadas anomalias severas na janela analisada.",
                severidade="baixa",
                evidencias=[],
            )
        )

    # Recomendações práticas
    recomendacoes: list[Recommendation] = []
    for sig in signals[:4]:
        s_id = sig.get("id", "")
        code = sig.get("code", "")
        subj = sig.get("subject", "a equipe")
        if code == "BUS_FACTOR_1":
            acao = f"Realizar pareamento e compartilhamento de conhecimento com {subj}"
            just = f"Mitiga o risco crítico de ponto único de falha identificado em {s_id}."
        elif code == "REVIEW_CONCENTRATION":
            acao = f"Redistribuir revisões de código entre os pares de {subj}"
            just = f"Alivia a sobrecarga de revisão e evita gargalo no fluxo registrado em {s_id}."
        elif code in ("LATE_RATE_HIGH", "LOW_COMPLETION"):
            acao = "Revisar o escopo e o planejamento das entregas da sprint"
            just = f"Reduz a taxa de atraso e melhora a previsibilidade apontada em {s_id}."
        elif code == "ISOLATED_MEMBER":
            acao = f"Integrar {subj} em tarefas colaborativas com outros membros"
            just = f"Evita silos e promove integração técnica conforme a evidência {s_id}."
        else:
            acao = f"Monitorar evolução do sinal {code}"
            just = f"Acompanhamento preventivo baseado na evidência {s_id}."

        recomendacoes.append(
            Recommendation(
                acao=acao[:120],
                justificativa=just,
                evidencias=[Evidence(ref=s_id)],
            )
        )

    if not recomendacoes:
        recomendacoes.append(
            Recommendation(
                acao="Manter o ritmo operacional atual",
                justificativa="Os indicadores observados permanecem dentro dos parâmetros esperados.",
                evidencias=[],
            )
        )

    lim_list = [str(l) for l in limits[:3]]
    if not lim_list:
        lim_list = ["Texto gerado por regras determinísticas."]

    return AnalysisSection(
        resumo=resumo,
        achados=achados[:5],
        recomendacoes=recomendacoes[:4],
        limitacoes=lim_list[:3],
    )
