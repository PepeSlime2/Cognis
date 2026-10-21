from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    """
    Referência a um item factual do bloco FATOS (ex.: 'S1', 'M3', 'P2').
    O LLM deve obrigatoriamente referenciar itens que existam em facts.
    """
    ref: str = Field(..., description="ID curto da evidência presente em FATOS (ex.: S1, M2)")

    model_config = ConfigDict(extra="ignore")


class Finding(BaseModel):
    """
    Um achado identificado na dinâmica da equipe baseado exclusivamente em evidências.
    """
    titulo: str = Field(..., description="Título curto do achado em português (máx. 100 caracteres)")
    descricao: str = Field(..., description="Descrição objetiva do padrão ou situação identificada")
    severidade: Literal["baixa", "media", "alta"] = Field(
        ..., description="Grau de severidade/impacto do achado"
    )
    evidencias: list[Evidence] = Field(
        default_factory=list,
        description="Lista de referências (ref) aos fatos que comprovam o achado",
    )

    model_config = ConfigDict(extra="ignore")


class Recommendation(BaseModel):
    """
    Recomendação de ação prática e verificável para o gestor.
    """
    acao: str = Field(..., description="Ação prática recomendada para o gestor")
    justificativa: str = Field(..., description="Justificativa contextual baseada nos dados")
    evidencias: list[Evidence] = Field(
        default_factory=list,
        description="Referências aos fatos que justificam a recomendação",
    )

    model_config = ConfigDict(extra="ignore")


class AnalysisSection(BaseModel):
    """
    Estrutura de uma seção de análise gerada pelo LLM ou preenchida por templates (SPEC §9.5).
    """
    resumo: str = Field(
        ...,
        max_length=600,
        description="Resumo contextual em texto corrido (≤ 600 caracteres)",
    )
    achados: list[Finding] = Field(
        default_factory=list,
        max_length=5,
        description="Lista de achados relevantes (≤ 5 itens)",
    )
    recomendacoes: list[Recommendation] = Field(
        default_factory=list,
        max_length=4,
        description="Ações práticas recomendadas (≤ 4 itens)",
    )
    limitacoes: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Limitações observadas nos dados disponíveis (≤ 3 itens)",
    )

    model_config = ConfigDict(extra="ignore")


class FactsResult(BaseModel):
    """
    Resultado produzido pelo facts_builder.
    O reverse_map fica estritamente no servidor para posterior desanonimização de exibição.
    """
    facts: dict[str, Any]
    reverse_map: dict[str, str] = Field(default_factory=dict)
    tokens_estimate: int = 0
