from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, Field


class KPIItem(BaseModel):
    label: str
    value: Any
    hint: str | None = None


class KPIsBlock(BaseModel):
    type: Literal["kpis"] = "kpis"
    items: list[KPIItem]


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    title: str | None = None
    columns: list[str]
    rows: list[list[Any]]


class ChartBlock(BaseModel):
    type: Literal["chart"] = "chart"
    kind: Literal["bar", "line", "pie"] = "bar"
    png_path: str | None = None
    caption: str = ""


class GraphImageBlock(BaseModel):
    type: Literal["graph_image"] = "graph_image"
    png_path: str | None = None
    caption: str = ""


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    origin: Literal["llm", "template", "data"] = "data"
    markdown: str


class CalloutBlock(BaseModel):
    type: Literal["callout"] = "callout"
    level: Literal["info", "warning", "success"] = "info"
    text: str


ReportBlock = Annotated[
    Union[KPIsBlock, TableBlock, ChartBlock, GraphImageBlock, TextBlock, CalloutBlock],
    Field(discriminator="type"),
]


class ReportSection(BaseModel):
    id: str
    title: str
    blocks: list[ReportBlock] = Field(default_factory=list)


class ReportAppendix(BaseModel):
    definitions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    ethical_note: str = (
        "Os indicadores descrevem padrões de colaboração e processo, não avaliam "
        "desempenho ou mérito individual (Lei de Goodhart). Não constituem ranking ou avaliação funcional."
    )


class ReportMeta(BaseModel):
    type: Literal["sprint", "gerencial", "individual", "gargalos", "colaboracao"]
    title: str
    project: str
    project_id: str
    window: dict[str, Any]
    generated_at: str
    model: str | None = None
    data_version: str | int | None = None
    anonymized: bool = False
    person_name: str | None = None


class ReportModel(BaseModel):
    """
    Modelo de dados JSON central que alimenta todos os formatos de exportação (HTML, DOCX, PDF)
    conforme especificado em SPEC §10.2.
    """
    meta: ReportMeta
    sections: list[ReportSection] = Field(default_factory=list)
    appendix: ReportAppendix = Field(default_factory=ReportAppendix)
