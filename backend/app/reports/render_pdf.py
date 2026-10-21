from __future__ import annotations

import base64
import html
import io
import re
from pathlib import Path
from typing import Any

import matplotlib
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image as PlatypusImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import (
    CalloutBlock,
    ChartBlock,
    GraphImageBlock,
    KPIsBlock,
    ReportModel,
    TableBlock,
    TextBlock,
)

# Cores institucionais do COGNIS
COLOR_PRIMARY = colors.HexColor("#4F46E5")  # Índigo
COLOR_TEXT_MAIN = colors.HexColor("#0F172A")  # Ardósia escuro
COLOR_TEXT_MUTED = colors.HexColor("#64748B")  # Texto secundário
COLOR_BG_CARD = colors.HexColor("#F8FAFC")
COLOR_HEADER_BG = colors.HexColor("#F1F5F9")
COLOR_BORDER = colors.HexColor("#E2E8F0")

COLOR_WARN_BG = colors.HexColor("#FFFBEB")
COLOR_WARN_BORDER = colors.HexColor("#D97706")
COLOR_INFO_BG = colors.HexColor("#F0F9FF")
COLOR_INFO_BORDER = colors.HexColor("#0284C7")
COLOR_SUCCESS_BG = colors.HexColor("#F0FDF4")
COLOR_SUCCESS_BORDER = colors.HexColor("#16A34A")

_FONTS_REGISTERED = False


def _ensure_fonts_registered() -> tuple[str, str]:
    """
    Registra fontes DejaVuSans e DejaVuSans-Bold a partir do pacote matplotlib (SPEC §10.3).
    Garante suporte completo a acentos da língua portuguesa (pt-BR) em PDF.
    Retorna os nomes das fontes (regular, bold).
    """
    global _FONTS_REGISTERED
    regular_name = "DejaVuSans"
    bold_name = "DejaVuSans-Bold"

    if _FONTS_REGISTERED:
        return regular_name, bold_name

    try:
        mpl_dir = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
        reg_file = mpl_dir / "DejaVuSans.ttf"
        bold_file = mpl_dir / "DejaVuSans-Bold.ttf"

        if reg_file.is_file():
            pdfmetrics.registerFont(TTFont(regular_name, str(reg_file)))
        else:
            regular_name = "Helvetica"

        if bold_file.is_file():
            pdfmetrics.registerFont(TTFont(bold_name, str(bold_file)))
        else:
            bold_name = "Helvetica-Bold"

        _FONTS_REGISTERED = True
    except Exception:
        regular_name = "Helvetica"
        bold_name = "Helvetica-Bold"

    return regular_name, bold_name


def _resolve_image_stream(png_path: str | None) -> io.BytesIO | str | None:
    """Resolve o caminho de imagem ou data URI em arquivo ou stream utilizável por PIL e ReportLab."""
    if not png_path:
        return None

    if png_path.startswith("data:image/"):
        try:
            _, b64_data = png_path.split(",", 1)
            raw = base64.b64decode(b64_data)
            return io.BytesIO(raw)
        except Exception:
            return None

    p = Path(png_path)
    if p.is_file():
        return str(p)

    return None


def _format_markdown_for_reportlab(md_text: str, regular_font: str, bold_font: str) -> list[str]:
    """
    Converte texto markdown em parágrafos compatíveis com ReportLab:
    - Trata tags <b>, <i>, <font>
    - Converte itens de lista
    """
    if not md_text:
        return []

    lines = md_text.split("\n")
    processed: list[str] = []

    for line in lines:
        s = line.strip()
        if not s:
            continue

        # Escapar caracteres HTML reservados, mas manter tags seguras
        escaped = html.escape(s)
        # Re-substituir negrito e itálico
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        escaped = re.sub(r"\*(.+?)\*", r"<i>\1</i>", escaped)
        escaped = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', escaped)

        if escaped.startswith("- "):
            item = escaped[2:].strip()
            processed.append(f"&bull; {item}")
        else:
            processed.append(escaped)

    return processed


def render_pdf_report(
    report: ReportModel | dict[str, Any],
    output_path: str | Path | None = None,
) -> bytes:
    """
    Renderiza um relatório COGNIS (ReportModel) em documento PDF formatado via ReportLab Platypus (SPEC §10.3).
    - Utiliza fontes DejaVuSans com suporte completo a acentos da língua portuguesa.
    - Metadados, tabelas de KPIs e dados estruturados com estilo profissional.
    - Imagens do grafo e gráficos embutidas em alta resolução com legendas.
    - Banner de conformidade ética e uso responsável das métricas (§13.4 e Lei de Goodhart).
    - Apêndice com definições de fórmulas e limitações de dados.
    - Se output_path for informado, salva em disco com extensão .pdf.
    - Retorna os bytes do arquivo PDF gerado.
    """
    if isinstance(report, dict):
        report_model = ReportModel.model_validate(report)
    else:
        report_model = report

    font_reg, font_bold = _ensure_fonts_registered()

    # Configuração de estilos ReportLab
    styles = getSampleStyleSheet()

    style_brand = ParagraphStyle(
        "ReportBrand",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=8.5,
        leading=10,
        textColor=COLOR_PRIMARY,
        spaceAfter=4,
    )

    style_title = ParagraphStyle(
        "ReportTitle",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=20,
        leading=24,
        textColor=COLOR_TEXT_MAIN,
        spaceAfter=10,
    )

    style_section_h = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=13,
        leading=16,
        textColor=COLOR_PRIMARY,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    )

    style_sub_h = ParagraphStyle(
        "SubHeading",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=10.5,
        leading=13,
        textColor=COLOR_TEXT_MAIN,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True,
    )

    style_body = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=9,
        leading=13,
        textColor=COLOR_TEXT_MAIN,
        spaceAfter=4,
    )

    style_meta_lbl = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=8,
        leading=10,
        textColor=COLOR_TEXT_MUTED,
    )

    style_meta_val = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=8.5,
        leading=11,
        textColor=COLOR_TEXT_MAIN,
    )

    style_caption = ParagraphStyle(
        "ImageCaption",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=8.5,
        leading=11,
        textColor=COLOR_TEXT_MUTED,
        alignment=1,  # Centralizado
        spaceBefore=4,
        spaceAfter=10,
    )

    style_callout = ParagraphStyle(
        "CalloutText",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=9,
        leading=12,
        textColor=COLOR_TEXT_MAIN,
    )

    style_footer = ParagraphStyle(
        "ReportFooter",
        parent=styles["Normal"],
        fontName=font_reg,
        fontSize=8,
        leading=10,
        textColor=COLOR_TEXT_MUTED,
        alignment=1,
        spaceBefore=14,
    )

    # Margens e área útil (A4 = 595.27 x 841.89 pt)
    usable_width = 595.27 - 72  # 523.27 pt

    bio = io.BytesIO()
    doc = SimpleDocTemplate(
        bio,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    story: list[Any] = []

    # 1. Cabeçalho e Título
    story.append(Paragraph("COGNIS — INTELIGÊNCIA DE COLABORAÇÃO", style_brand))
    story.append(Paragraph(report_model.meta.title, style_title))

    # Tabela de Metadados
    meta_rows = [
        [
            Paragraph("TIPO DE RELATÓRIO", style_meta_lbl),
            Paragraph(f"{report_model.meta.type.capitalize()}{' (Anonimizado)' if report_model.meta.anonymized else ''}", style_meta_val),
            Paragraph("PROJETO", style_meta_lbl),
            Paragraph(report_model.meta.project, style_meta_val),
        ],
        [
            Paragraph("PERÍODO", style_meta_lbl),
            Paragraph(
                f"{report_model.meta.window.get('label') or ''} ({report_model.meta.window.get('from', '—')} até {report_model.meta.window.get('to', '—')})".strip(),
                style_meta_val,
            ),
            Paragraph("GERADO EM", style_meta_lbl),
            Paragraph(report_model.meta.generated_at[:19].replace("T", " ") + " UTC", style_meta_val),
        ],
    ]
    if report_model.meta.person_name:
        meta_rows.append([
            Paragraph("COLABORADOR", style_meta_lbl),
            Paragraph(report_model.meta.person_name, style_meta_val),
            Paragraph("VERSÃO DADOS", style_meta_lbl),
            Paragraph(str(report_model.meta.data_version or "1.0"), style_meta_val),
        ])

    meta_tbl = Table(
        meta_rows,
        colWidths=[110, 150, 100, 163],
    )
    meta_tbl.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), COLOR_BG_CARD),
            ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(meta_tbl)
    story.append(Spacer(1, 8))

    # Banner Ético / Uso Responsável (§13.4)
    ethical_p = Paragraph(
        f"<b>Nota de Uso Responsável:</b> <i>{report_model.appendix.ethical_note}</i>",
        style_callout,
    )
    ethical_tbl = Table([[ethical_p]], colWidths=[usable_width])
    ethical_tbl.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), COLOR_BG_CARD),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEBEFORE", (0, 0), (0, 0), 3.0, COLOR_PRIMARY),
        ])
    )
    story.append(ethical_tbl)
    story.append(Spacer(1, 10))

    # 2. Seções
    for section in report_model.sections:
        story.append(Paragraph(section.title, style_section_h))
        story.append(HRFlowable(width="100%", thickness=1, color=COLOR_BORDER, spaceAfter=8))

        for block in section.blocks:
            if isinstance(block, KPIsBlock):
                items = block.items
                if items:
                    kpi_rows: list[list[Any]] = [
                        [
                            Paragraph("<b>Indicador</b>", style_body),
                            Paragraph("<b>Valor</b>", style_body),
                            Paragraph("<b>Referência / Meta</b>", style_body),
                        ]
                    ]
                    for it in items:
                        kpi_rows.append([
                            Paragraph(it.label, style_body),
                            Paragraph(f"<font color='{COLOR_PRIMARY.hexval()}'><b>{it.value}</b></font>", style_body),
                            Paragraph(f"<font color='{COLOR_TEXT_MUTED.hexval()}'>{it.hint or '—'}</font>", style_body),
                        ])

                    kpi_tbl = Table(kpi_rows, colWidths=[200, 120, 203])
                    kpi_tbl.setStyle(
                        TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
                            ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
                            ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ])
                    )
                    story.append(kpi_tbl)
                    story.append(Spacer(1, 8))

            elif isinstance(block, TableBlock):
                if block.title:
                    story.append(Paragraph(f"<b>{block.title}</b>", style_sub_h))

                num_cols = len(block.columns)
                if num_cols > 0:
                    col_w = usable_width / num_cols
                    tbl_rows: list[list[Any]] = [
                        [Paragraph(f"<b>{c}</b>", style_body) for c in block.columns]
                    ]
                    for r_data in block.rows:
                        tbl_rows.append([Paragraph(str(val), style_body) for val in r_data])

                    t = Table(tbl_rows, colWidths=[col_w] * num_cols)
                    t_style = [
                        ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
                        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
                        ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ]
                    # Zebra striping
                    for r_idx in range(1, len(tbl_rows)):
                        if r_idx % 2 == 0:
                            t_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#FAFAFB")))

                    t.setStyle(TableStyle(t_style))
                    story.append(t)
                    story.append(Spacer(1, 8))

            elif isinstance(block, (ChartBlock, GraphImageBlock)):
                img_stream = _resolve_image_stream(block.png_path)
                if img_stream is not None:
                    try:
                        # Calcular proporção real via PIL
                        with PILImage.open(img_stream) as pil_im:
                            orig_w, orig_h = pil_im.size
                            aspect = orig_h / max(1, orig_w)

                        target_w = 460
                        target_h = target_w * aspect

                        # Se img_stream for BytesIO, rebobinar antes de entregar ao ReportLab
                        if isinstance(img_stream, io.BytesIO):
                            img_stream.seek(0)

                        img_flowable = PlatypusImage(img_stream, width=target_w, height=target_h)
                        story.append(img_flowable)
                        if block.caption:
                            story.append(Paragraph(block.caption, style_caption))
                    except Exception:
                        story.append(Paragraph(f"<i>[Erro ao carregar imagem: {block.caption}]</i>", style_caption))
                else:
                    story.append(
                        Paragraph(f"<i>[ Imagem não disponível: {block.caption or 'gráfico'} ]</i>", style_caption)
                    )
                story.append(Spacer(1, 6))

            elif isinstance(block, TextBlock):
                origin_badge = (
                    "<b>✦ ANÁLISE IA LOCAL (Llama 3.1 8B)</b>"
                    if block.origin == "llm"
                    else ("<b>⚙ ANÁLISE DETERMINÍSTICA (Regras)</b>" if block.origin == "template" else "<b>FATOS E DADOS</b>")
                )
                story.append(Paragraph(f"<font color='{COLOR_PRIMARY.hexval()}'>{origin_badge}</font>", style_body))
                lines = _format_markdown_for_reportlab(block.markdown, font_reg, font_bold)
                for l_str in lines:
                    story.append(Paragraph(l_str, style_body))
                story.append(Spacer(1, 6))

            elif isinstance(block, CalloutBlock):
                border_color = COLOR_INFO_BORDER
                bg_color = COLOR_INFO_BG
                prefix = "<b>[INFORMAÇÃO]</b> "

                if block.level == "warning":
                    border_color = COLOR_WARN_BORDER
                    bg_color = COLOR_WARN_BG
                    prefix = "<b>[AVISO DE ATENÇÃO]</b> "
                elif block.level == "success":
                    border_color = COLOR_SUCCESS_BORDER
                    bg_color = COLOR_SUCCESS_BG
                    prefix = "<b>[DESTAQUE POSITIVO]</b> "

                c_para = Paragraph(f"{prefix}{block.text}", style_callout)
                c_tbl = Table([[c_para]], colWidths=[usable_width])
                c_tbl.setStyle(
                    TableStyle([
                        ("BACKGROUND", (0, 0), (-1, -1), bg_color),
                        ("BOX", (0, 0), (-1, -1), 0.5, border_color),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LINEBEFORE", (0, 0), (0, 0), 3.0, border_color),
                    ])
                )
                story.append(c_tbl)
                story.append(Spacer(1, 8))

    # 3. Apêndice e Metodologia
    story.append(KeepTogether([
        Paragraph("Apêndice e Metodologia", style_section_h),
        HRFlowable(width="100%", thickness=1, color=COLOR_BORDER, spaceAfter=8),
    ]))

    if report_model.appendix.definitions:
        story.append(Paragraph("<b>Definições das Métricas</b>", style_sub_h))
        for def_str in report_model.appendix.definitions:
            story.append(Paragraph(f"&bull; <font color='{COLOR_TEXT_MUTED.hexval()}'>{def_str}</font>", style_body))
        story.append(Spacer(1, 6))

    if report_model.appendix.limitations:
        story.append(Paragraph("<b>Limitações dos Dados</b>", style_sub_h))
        for lim_str in report_model.appendix.limitations:
            story.append(Paragraph(f"&bull; <font color='{COLOR_TEXT_MUTED.hexval()}'>{lim_str}</font>", style_body))
        story.append(Spacer(1, 6))

    story.append(
        Paragraph("COGNIS — Análise determinística e interpretação contextual de grafos de colaboração.", style_footer)
    )

    doc.build(story)
    pdf_bytes = bio.getvalue()

    if output_path is not None:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(pdf_bytes)

    return pdf_bytes
