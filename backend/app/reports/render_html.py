from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import jinja2

from .charts import image_bytes_to_base64
from .models import (
    CalloutBlock,
    ChartBlock,
    GraphImageBlock,
    KPIsBlock,
    ReportModel,
    TableBlock,
    TextBlock,
)


def _resolve_image_data_uri(png_path: str | None) -> str | None:
    """
    Resolve um caminho de imagem PNG para data URI base64.
    Se já for data URI, retorna diretamente.
    Se for um caminho existente no disco, lê os bytes e converte para base64.
    """
    if not png_path:
        return None
    if png_path.startswith("data:image/"):
        return png_path

    try:
        p = Path(png_path)
        if p.is_file():
            raw_bytes = p.read_bytes()
            return image_bytes_to_base64(raw_bytes)
    except Exception:
        pass
    return None


def _simple_markdown_to_html(md_text: str) -> str:
    """
    Converte texto markdown seguro básico para HTML limpo sem dependências externas:
    - Escapa tags HTML não confiáveis
    - Converte **negrito**, *itálico*, `código inline`
    - Converte listas com marcadores (-)
    - Divide em parágrafos <p>
    """
    if not md_text:
        return ""

    escaped = html.escape(md_text)

    # Substituição inline
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)

    # Tratar blocos de linhas
    lines = escaped.split("\n")
    html_parts: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            if not in_list:
                html_parts.append('<ul class="report-list">')
                in_list = True
            item_text = stripped[2:].strip()
            html_parts.append(f"<li>{item_text}</li>")
        else:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            if stripped:
                html_parts.append(f"<p>{stripped}</p>")

    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ meta.title }} — COGNIS</title>
  <style>
    /* Reset & Variáveis */
    *, *::before, *::after {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    :root {
      --bg-body: #f8fafc;
      --bg-card: #ffffff;
      --border-color: #e2e8f0;
      --border-subtle: #cbd5e1;
      --text-main: #0f172a;
      --text-muted: #64748b;
      --text-light: #94a3b8;
      --accent: #4f46e5;
      --accent-light: #eef2ff;
      --accent-dark: #3730a3;
      --info-bg: #f0f9ff;
      --info-border: #0284c7;
      --info-text: #0369a1;
      --warning-bg: #fffbeb;
      --warning-border: #d97706;
      --warning-text: #92400e;
      --success-bg: #f0fdf4;
      --success-border: #16a34a;
      --success-text: #166534;
      --badge-llm-bg: #ecfdf5;
      --badge-llm-text: #065f46;
      --badge-llm-border: #a7f3d0;
      --badge-tmpl-bg: #fffbeb;
      --badge-tmpl-text: #92400e;
      --badge-tmpl-border: #fde68a;
    }

    body {
      background-color: var(--bg-body);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.6;
      font-size: 15px;
      padding: 32px 16px;
    }

    .report-container {
      max-width: 980px;
      margin: 0 auto;
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 40px;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
    }

    /* Cabeçalho */
    .report-header {
      border-bottom: 2px solid var(--border-color);
      padding-bottom: 24px;
      margin-bottom: 32px;
    }

    .header-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 12px;
      flex-wrap: wrap;
      gap: 12px;
    }

    .brand-title {
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.1em;
      color: var(--accent);
      text-transform: uppercase;
    }

    .meta-badges {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .badge {
      font-size: 12px;
      padding: 3px 10px;
      border-radius: 9999px;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      border: 1px solid transparent;
    }

    .badge-report-type {
      background: var(--accent-light);
      color: var(--accent);
      border-color: #c7d2fe;
      text-transform: capitalize;
    }

    .badge-anonymized {
      background: #f1f5f9;
      color: #475569;
      border-color: var(--border-subtle);
    }

    .report-title {
      font-size: 28px;
      font-weight: 800;
      color: var(--text-main);
      line-height: 1.25;
      margin-bottom: 16px;
    }

    .header-details-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      font-size: 13px;
      color: var(--text-muted);
      background: #f8fafc;
      padding: 16px;
      border-radius: 8px;
      border: 1px solid var(--border-color);
    }

    .header-detail-item strong {
      color: var(--text-main);
      display: block;
      margin-bottom: 2px;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    /* Nota Ética de Destaque */
    .ethical-banner {
      background-color: #f8fafc;
      border-left: 4px solid var(--accent);
      padding: 14px 18px;
      border-radius: 0 8px 8px 0;
      margin-bottom: 32px;
      font-size: 13px;
      color: #334155;
    }

    .ethical-banner strong {
      color: var(--accent-dark);
    }

    /* Seções */
    .report-section {
      margin-bottom: 40px;
    }

    .section-title {
      font-size: 20px;
      font-weight: 700;
      color: var(--text-main);
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 8px;
      margin-bottom: 20px;
    }

    /* Bloco KPIs */
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }

    .kpi-card {
      background: #ffffff;
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
      border-top: 3px solid var(--accent);
    }

    .kpi-label {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.03em;
      margin-bottom: 6px;
    }

    .kpi-value {
      font-size: 26px;
      font-weight: 800;
      color: var(--text-main);
      line-height: 1.1;
      margin-bottom: 4px;
    }

    .kpi-hint {
      font-size: 12px;
      color: var(--text-light);
    }

    /* Bloco Tabela */
    .table-container {
      margin-bottom: 24px;
      overflow-x: auto;
      border: 1px solid var(--border-color);
      border-radius: 8px;
    }

    .table-title {
      font-size: 14px;
      font-weight: 600;
      padding: 10px 16px;
      background: #f8fafc;
      border-bottom: 1px solid var(--border-color);
      color: var(--text-main);
    }

    .report-table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 13px;
    }

    .report-table th {
      background: #f1f5f9;
      color: var(--text-main);
      font-weight: 700;
      padding: 10px 16px;
      border-bottom: 1px solid var(--border-color);
    }

    .report-table td {
      padding: 10px 16px;
      border-bottom: 1px solid #f1f5f9;
      color: var(--text-main);
    }

    .report-table tr:last-child td {
      border-bottom: none;
    }

    .report-table tr:nth-child(even) {
      background-color: #fafafb;
    }

    /* Imagens e Gráficos */
    .image-block {
      margin-bottom: 28px;
      text-align: center;
    }

    .image-frame {
      display: inline-block;
      max-width: 100%;
      background: #ffffff;
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 8px;
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
    }

    .image-frame img {
      max-width: 100%;
      height: auto;
      border-radius: 4px;
      display: block;
    }

    .image-caption {
      font-size: 13px;
      color: var(--text-muted);
      margin-top: 8px;
      font-style: italic;
    }

    .image-placeholder {
      padding: 40px 20px;
      background: #f8fafc;
      border: 2px dashed var(--border-subtle);
      border-radius: 8px;
      color: var(--text-muted);
      font-size: 13px;
    }

    /* Bloco de Texto & Selos */
    .text-block {
      background: #ffffff;
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
    }

    .origin-badge-container {
      margin-bottom: 12px;
    }

    .badge-origin-llm {
      background: var(--badge-llm-bg);
      color: var(--badge-llm-text);
      border-color: var(--badge-llm-border);
    }

    .badge-origin-template {
      background: var(--badge-tmpl-bg);
      color: var(--badge-tmpl-text);
      border-color: var(--badge-tmpl-border);
    }

    .badge-origin-data {
      background: #f1f5f9;
      color: #475569;
      border-color: var(--border-subtle);
    }

    .text-content p {
      margin-bottom: 12px;
      color: #334155;
    }

    .text-content p:last-child {
      margin-bottom: 0;
    }

    .text-content strong {
      color: var(--text-main);
    }

    .text-content code {
      background: #f1f5f9;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 13px;
      color: #0f172a;
    }

    .report-list {
      padding-left: 20px;
      margin-bottom: 12px;
      color: #334155;
    }

    .report-list li {
      margin-bottom: 6px;
    }

    /* Bloco Callout */
    .callout-block {
      border-left: 4px solid var(--info-border);
      background: var(--info-bg);
      color: var(--info-text);
      padding: 14px 18px;
      border-radius: 0 8px 8px 0;
      margin-bottom: 24px;
      font-size: 14px;
    }

    .callout-warning {
      border-left-color: var(--warning-border);
      background: var(--warning-bg);
      color: var(--warning-text);
    }

    .callout-success {
      border-left-color: var(--success-border);
      background: var(--success-bg);
      color: var(--success-text);
    }

    /* Apêndice */
    .report-appendix {
      border-top: 2px solid var(--border-color);
      padding-top: 28px;
      margin-top: 40px;
    }

    .appendix-title {
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 16px;
      color: var(--text-main);
    }

    .appendix-section {
      margin-bottom: 20px;
    }

    .appendix-subtitle {
      font-size: 14px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-muted);
      margin-bottom: 8px;
    }

    .appendix-list {
      padding-left: 20px;
      font-size: 13px;
      color: var(--text-muted);
    }

    .appendix-list li {
      margin-bottom: 4px;
    }

    /* Rodapé */
    .report-footer {
      border-top: 1px solid var(--border-color);
      padding-top: 16px;
      margin-top: 32px;
      text-align: center;
      font-size: 12px;
      color: var(--text-light);
    }

    /* Modo Impressão */
    @media print {
      body {
        background: #ffffff;
        padding: 0;
        font-size: 12pt;
      }
      .report-container {
        border: none;
        box-shadow: none;
        padding: 0;
        max-width: 100%;
      }
      .kpi-card, .table-container, .image-frame, .text-block, .report-section {
        page-break-inside: avoid;
      }
    }
  </style>
</head>
<body>
  <div class="report-container">
    <!-- Cabeçalho -->
    <header class="report-header">
      <div class="header-top">
        <span class="brand-title">COGNIS — Inteligência de Colaboração</span>
        <div class="meta-badges">
          <span class="badge badge-report-type">Relatório {{ meta.type }}</span>
          {% if meta.anonymized %}
            <span class="badge badge-anonymized">Anonimizado</span>
          {% endif %}
        </div>
      </div>

      <h1 class="report-title">{{ meta.title }}</h1>

      <div class="header-details-grid">
        <div class="header-detail-item">
          <strong>Projeto</strong>
          <span>{{ meta.project }}</span>
        </div>
        <div class="header-detail-item">
          <strong>Período</strong>
          <span>
            {% if meta.window.label %}{{ meta.window.label }} ({% endif %}
            {{ meta.window.get('from', '—') }} até {{ meta.window.get('to', '—') }}
            {% if meta.window.label %}){% endif %}
          </span>
        </div>
        <div class="header-detail-item">
          <strong>Gerado em</strong>
          <span>{{ meta.generated_at }}</span>
        </div>
        <div class="header-detail-item">
          <strong>Versão dos Dados</strong>
          <span>{{ meta.data_version or '1.0' }}</span>
        </div>
        {% if meta.person_name %}
        <div class="header-detail-item">
          <strong>Colaborador</strong>
          <span>{{ meta.person_name }}</span>
        </div>
        {% endif %}
      </div>
    </header>

    <!-- Banner de Uso Responsável (SPEC §13.4) -->
    <div class="ethical-banner">
      <strong>Nota de Uso Responsável:</strong>
      {{ appendix.ethical_note }}
    </div>

    <!-- Seções de Conteúdo -->
    <main>
      {% for section in sections %}
      <section class="report-section" id="{{ section.id }}">
        <h2 class="section-title">{{ section.title }}</h2>

        {% for block in section.blocks %}
          {% if block.type == "kpis" %}
            <div class="kpi-grid">
              {% for item in block['items'] %}
                <div class="kpi-card">
                  <div class="kpi-label">{{ item.label }}</div>
                  <div class="kpi-value">{{ item.value }}</div>
                  {% if item.hint %}
                    <div class="kpi-hint">{{ item.hint }}</div>
                  {% endif %}
                </div>
              {% endfor %}
            </div>

          {% elif block.type == "table" %}
            <div class="table-container">
              {% if block.title %}
                <div class="table-title">{{ block.title }}</div>
              {% endif %}
              <table class="report-table">
                <thead>
                  <tr>
                    {% for col in block.columns %}
                      <th>{{ col }}</th>
                    {% endfor %}
                  </tr>
                </thead>
                <tbody>
                  {% for row in block.rows %}
                    <tr>
                      {% for cell in row %}
                        <td>{{ cell }}</td>
                      {% endfor %}
                    </tr>
                  {% endfor %}
                </tbody>
              </table>
            </div>

          {% elif block.type == "chart" or block.type == "graph_image" %}
            <div class="image-block">
              {% set data_uri = block.resolved_data_uri %}
              {% if data_uri %}
                <div class="image-frame">
                  <img src="{{ data_uri }}" alt="{{ block.caption }}">
                </div>
                {% if block.caption %}
                  <div class="image-caption">{{ block.caption }}</div>
                {% endif %}
              {% else %}
                <div class="image-placeholder">
                  [ Imagem não disponível: {{ block.caption or "gráfico" }} ]
                </div>
              {% endif %}
            </div>

          {% elif block.type == "text" %}
            <div class="text-block">
              <div class="origin-badge-container">
                {% if block.origin == "llm" %}
                  <span class="badge badge-origin-llm">✦ Análise IA Local (Llama 3.1 8B)</span>
                {% elif block.origin == "template" %}
                  <span class="badge badge-origin-template">⚙ Análise Determinística (Regras)</span>
                {% else %}
                  <span class="badge badge-origin-data">Fatos e Dados</span>
                {% endif %}
              </div>
              <div class="text-content">
                {{ block.rendered_html | safe }}
              </div>
            </div>

          {% elif block.type == "callout" %}
            <div class="callout-block callout-{{ block.level }}">
              {{ block.text }}
            </div>
          {% endif %}
        {% endfor %}
      </section>
      {% endfor %}
    </main>

    <!-- Apêndice -->
    <footer class="report-appendix">
      <h3 class="appendix-title">Apêndice e Metodologia</h3>

      {% if appendix.definitions %}
      <div class="appendix-section">
        <h4 class="appendix-subtitle">Definições das Métricas</h4>
        <ul class="appendix-list">
          {% for def_item in appendix.definitions %}
            <li>{{ def_item }}</li>
          {% endfor %}
        </ul>
      </div>
      {% endif %}

      {% if appendix.limitations %}
      <div class="appendix-section">
        <h4 class="appendix-subtitle">Limitações dos Dados</h4>
        <ul class="appendix-list">
          {% for lim_item in appendix.limitations %}
            <li>{{ lim_item }}</li>
          {% endfor %}
        </ul>
      </div>
      {% endif %}

      <div class="report-footer">
        COGNIS — Análise determinística e interpretação contextual de grafos de colaboração.
      </div>
    </footer>
  </div>
</body>
</html>
"""


def render_html_report(
    report: ReportModel | dict[str, Any],
    output_path: str | Path | None = None,
) -> str:
    """
    Renderiza um relatório COGNIS (ReportModel) em um único arquivo HTML autocontido (SPEC §10.3).
    - Utiliza Jinja2 para montagem segura e determinística do documento.
    - CSS inline com tipografia de sistema, paleta harmônica e regras de impressão (@media print).
    - Imagens (gráficos e grafo) embutidas diretamente como data URI base64 para funcionamento 100% offline.
    - Se output_path for informado, salva o arquivo gerado em disco com codificação UTF-8.
    """
    if isinstance(report, dict):
        report_model = ReportModel.model_validate(report)
    else:
        report_model = report

    # Preparar blocos enriquecidos para o template
    prepared_sections: list[dict[str, Any]] = []

    for section in report_model.sections:
        prepared_blocks: list[dict[str, Any]] = []
        for block in section.blocks:
            block_dict = block.model_dump()
            b_type = block.type

            if b_type in ("chart", "graph_image"):
                png_path = getattr(block, "png_path", None)
                block_dict["resolved_data_uri"] = _resolve_image_data_uri(png_path)

            elif b_type == "text":
                raw_md = getattr(block, "markdown", "")
                block_dict["rendered_html"] = _simple_markdown_to_html(raw_md)

            prepared_blocks.append(block_dict)

        prepared_sections.append({
            "id": section.id,
            "title": section.title,
            "blocks": prepared_blocks,
        })

    env = jinja2.Environment(autoescape=True)
    template = env.from_string(HTML_TEMPLATE)

    rendered_html = template.render(
        meta=report_model.meta.model_dump(),
        sections=prepared_sections,
        appendix=report_model.appendix.model_dump(),
    )

    if output_path is not None:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rendered_html, encoding="utf-8")

    return rendered_html
