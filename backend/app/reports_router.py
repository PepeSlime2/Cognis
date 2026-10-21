from __future__ import annotations

import datetime as dt
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_router import get_current_user_id
from .database import get_neo4j_driver
from .db import repository, session as db_session
from .db.models import Project, Report
from .db.session import get_db_session
from .graph.collab_graph import build_collab_graph
from .graph.facts import load_facts_from_neo4j
from .llm.pipeline import run_analysis_pipeline
from .llm.schemas import AnalysisSection
from .llm.templates import generate_template_analysis
from .metrics import service
from .metrics.windows import default_window, parse_window, window_from_sprint
from .reports.builder import build_report
from .reports.charts import render_graph_image
from .reports.models import ReportModel
from .reports.render_docx import render_docx_report
from .reports.render_html import render_html_report
from .reports.render_pdf import render_pdf_report

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reports"])

# Executor para geração de relatórios em segundo plano
_reports_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cognis-report")

ReportFormat = Literal["html", "docx", "pdf"]


class ReportCreateRequest(BaseModel):
    type: Literal["sprint", "gerencial", "individual", "gargalos", "colaboracao"] = Field(
        ..., description="Tipo do relatório"
    )
    window: str | None = Field(None, description="Janela relativa: 7d, 14d, 30d, 90d")
    from_date: str | None = Field(None, alias="from", description="Data início YYYY-MM-DD")
    to_date: str | None = Field(None, alias="to", description="Data término YYYY-MM-DD")
    sprint_id: str | None = Field(None, description="ID da sprint para delimitar a janela")
    person_uid: str | None = Field(None, description="UID da pessoa (obrigatório para relatório individual)")
    formats: list[ReportFormat] = Field(
        default=["html", "docx", "pdf"],
        description="Formatos a serem gerados",
    )
    include_ai: bool = Field(True, description="Incluir análise e recomendações de IA (com fallback)")
    anonymize: bool = Field(False, description="Anonimizar nomes e dados no relatório")
    wait: bool = Field(False, description="Aguardar conclusão síncrona da geração")

    model_config = ConfigDict(populate_by_name=True)


def _format_report_dict(report: Report) -> dict[str, Any]:
    return {
        "id": report.id,
        "report_id": report.id,
        "project_id": report.project_id,
        "type": report.type,
        "status": report.status,
        "window": {
            "from": report.window_from.isoformat() if report.window_from else None,
            "to": report.window_to.isoformat() if report.window_to else None,
        },
        "person_uid": report.person_uid,
        "formats": list(report.files_json.keys()) if report.files_json else [],
        "files": report.files_json or {},
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


def _resolve_report_window(
    project: Project,
    db: Session,
    window_param: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    sprint_id: str | None = None,
):
    from .db.models import Sprint

    if sprint_id:
        sprint = db.execute(
            select(Sprint).where(Sprint.id == sprint_id, Sprint.project_id == project.id)
        ).scalar_one_or_none()
        if sprint is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sprint não encontrada",
            )
        return window_from_sprint(sprint, timezone=project.timezone)

    if from_date and to_date:
        try:
            return parse_window(from_date, to_date, timezone=project.timezone)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(err),
            ) from err

    if window_param:
        try:
            days = int(window_param.lower().rstrip("d"))
            return default_window(timezone=project.timezone, days=days)
        except Exception:
            pass

    return default_window(timezone=project.timezone, days=30)


def _run_report_generation(
    report_id: str,
    project_id: str,
    report_type: str,
    window_from_iso: str,
    window_to_iso: str,
    person_uid: str | None,
    formats: list[ReportFormat],
    include_ai: bool,
    anonymize: bool,
    db: Session | None = None,
    neo4j_driver: Any | None = None,
) -> None:
    """Função de trabalho que gera o ReportModel e todos os arquivos em disco."""
    close_db = False
    close_driver = False
    if db is None:
        db = db_session.SessionLocal()
        close_db = True
    if neo4j_driver is None:
        from .database import create_neo4j_driver
        neo4j_driver = create_neo4j_driver()
        close_driver = True

    try:
        report = db.execute(select(Report).where(Report.id == report_id)).scalar_one_or_none()
        if not report:
            return

        report.status = "processing"
        db.commit()

        project = db.execute(select(Project).where(Project.id == project_id)).scalar_one_or_none()
        if not project:
            report.status = "failed"
            db.commit()
            return

        window = parse_window(window_from_iso, window_to_iso, timezone=project.timezone)

        # 1. Obter MetricsBundle
        bundle = service.get_metrics_bundle(neo4j_driver, db, project, window)

        # 2. Análise de IA ou Template
        analysis_section: AnalysisSection | None = None
        analysis_source: str | None = None

        if include_ai:
            try:
                # Executa pipeline com fallback transparente
                pipe_res = run_analysis_pipeline(
                    neo4j_driver=neo4j_driver,
                    db=db,
                    project=project,
                    window=window,
                    scope="person" if report_type == "individual" else ("risks" if report_type == "gargalos" else "team"),
                    person_uid=person_uid,
                    anonymize=anonymize,
                    force_template=False,
                )
                analysis_section = pipe_res.section
                analysis_source = pipe_res.source
            except Exception as err:
                logger.warning("Falha ao gerar análise de IA para relatório %s; usando template: %s", report_id, err)
                analysis_section = generate_template_analysis(
                    scope="person" if report_type == "individual" else "team",
                    bundle=bundle,
                )
                analysis_source = "template"

        # 3. Diretório de armazenamento isolado (SPEC §10.3)
        storage_dir = Path("storage/reports") / project_id / report_id
        storage_dir.mkdir(parents=True, exist_ok=True)

        # 4. Gerar Imagem do Grafo
        graph_png_path: Path | None = None
        try:
            facts = load_facts_from_neo4j(neo4j_driver, project.id, window)
            settings = repository.get_project_settings(project)
            collab = build_collab_graph(facts, min_weight=float(settings.get("min_edge_weight", 1.0)))
            G = collab.graph_undirected

            # Labels de pessoas
            node_labels: dict[str, str] = {}
            for p_fact in facts.people:
                node_labels[p_fact.uid] = p_fact.display_name

            # Comunidades a partir das métricas calculadas
            comm_dict: dict[str, Any] = {}
            comm_metric = bundle.get("metrics", {}).get("graph.community", {}).get("values")
            if isinstance(comm_metric, dict):
                comm_dict = comm_metric

            graph_png_path = storage_dir / "graph.png"
            render_graph_image(
                graph=G,
                node_labels=node_labels,
                communities=comm_dict,
                output_path=graph_png_path,
                anonymize=anonymize,
            )
        except Exception as err:
            logger.warning("Não foi possível renderizar imagem do grafo para o relatório %s: %s", report_id, err)
            graph_png_path = None

        # 5. Nome do colaborador alvo para relatório individual
        target_person_name: str | None = None
        if person_uid:
            override = repository.get_person_override(db, project.id, person_uid)
            if override and override.display_name:
                target_person_name = override.display_name
            else:
                target_person_name = person_uid

        # 6. Construir ReportModel unificado
        report_model: ReportModel = build_report(
            report_type=report_type,  # type: ignore[arg-type]
            bundle=bundle,
            project_name=project.name,
            project_id=project.id,
            analysis_section=analysis_section,
            analysis_source=analysis_source,
            target_person_uid=person_uid,
            target_person_name=target_person_name,
            anonymize=anonymize,
            graph_png_path=str(graph_png_path) if graph_png_path and graph_png_path.is_file() else None,
        )

        # Salvar ReportModel JSON para reprodutibilidade (SPEC §10.2)
        model_json_path = storage_dir / "report_model.json"
        model_json_path.write_text(report_model.model_dump_json(indent=2), encoding="utf-8")

        # 7. Renderizar Formatos Solicitados
        files_map: dict[str, str] = {}

        if "html" in formats:
            html_path = storage_dir / "report.html"
            render_html_report(report_model, output_path=html_path)
            files_map["html"] = str(html_path)

        if "docx" in formats:
            docx_path = storage_dir / "report.docx"
            render_docx_report(report_model, output_path=docx_path)
            files_map["docx"] = str(docx_path)

        if "pdf" in formats:
            pdf_path = storage_dir / "report.pdf"
            render_pdf_report(report_model, output_path=pdf_path)
            files_map["pdf"] = str(pdf_path)

        # 8. Persistir Conclusão
        report.status = "completed"
        report.model_json_path = str(model_json_path)
        report.files_json = files_map
        db.commit()

    except Exception as exc:
        logger.exception("Erro ao gerar relatório %s: %s", report_id, exc)
        try:
            report = db.execute(select(Report).where(Report.id == report_id)).scalar_one_or_none()
            if report:
                report.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        if close_driver and neo4j_driver is not None:
            try:
                neo4j_driver.close()
            except Exception:
                pass
        if close_db and db is not None:
            db.close()


@router.post("/projects/{pid}/reports", status_code=status.HTTP_202_ACCEPTED)
def create_report(
    pid: str,
    payload: ReportCreateRequest,
    response: Response,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
    neo4j_driver: Any = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    """
    Solicita a geração de um relatório para o projeto (SPEC §11, §10.3).
    - Valida isolamento estrito de tenant (retorna 404 se o projeto não pertencer ao usuário).
    - Valida pessoa obrigatória se o tipo for 'individual'.
    - Suporta execução assíncrona (202 Accepted) ou síncrona com ?wait=True (200 OK).
    """
    project = repository.get_project_for_user(db, pid, user_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projeto não encontrado",
        )

    if payload.type == "individual" and not payload.person_uid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O campo 'person_uid' é obrigatório para relatórios do tipo individual",
        )

    window = _resolve_report_window(
        project=project,
        db=db,
        window_param=payload.window,
        from_date=payload.from_date,
        to_date=payload.to_date,
        sprint_id=payload.sprint_id,
    )

    report_id = str(uuid.uuid4())
    report = Report(
        id=report_id,
        project_id=project.id,
        type=payload.type,
        window_from=window.start_utc,
        window_to=window.end_utc,
        person_uid=payload.person_uid,
        status="pending",
        files_json={},
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    if payload.wait:
        _run_report_generation(
            report_id=report_id,
            project_id=project.id,
            report_type=payload.type,
            window_from_iso=window.start_date,
            window_to_iso=window.end_date,
            person_uid=payload.person_uid,
            formats=payload.formats,
            include_ai=payload.include_ai,
            anonymize=payload.anonymize,
            db=db,
            neo4j_driver=neo4j_driver,
        )
        db.refresh(report)
        response.status_code = status.HTTP_200_OK
        return _format_report_dict(report)

    # Execução em background
    _reports_executor.submit(
        _run_report_generation,
        report_id=report_id,
        project_id=project.id,
        report_type=payload.type,
        window_from_iso=window.start_date,
        window_to_iso=window.end_date,
        person_uid=payload.person_uid,
        formats=payload.formats,
        include_ai=payload.include_ai,
        anonymize=payload.anonymize,
    )

    return _format_report_dict(report)


@router.get("/reports/{id}")
def get_report(
    id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Recupera os detalhes e status de um relatório por ID.
    Garante que o relatório pertence a um projeto do usuário autenticado (404 caso contrário).
    """
    report = db.execute(select(Report).where(Report.id == id)).scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório não encontrado",
        )

    project = repository.get_project_for_user(db, report.project_id, user_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório não encontrado",
        )

    return _format_report_dict(report)


@router.get("/projects/{pid}/reports")
def list_project_reports(
    pid: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Lista todos os relatórios gerados para o projeto.
    Garante isolamento por tenant (404 se o projeto não pertencer ao usuário).
    """
    project = repository.get_project_for_user(db, pid, user_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projeto não encontrado",
        )

    reports = db.execute(
        select(Report)
        .where(Report.project_id == pid)
        .order_by(Report.created_at.desc())
    ).scalars().all()

    return [_format_report_dict(r) for r in reports]


@router.get("/reports/{id}/download")
def download_report(
    id: str,
    format: ReportFormat = Query(..., description="Formato desejado: html, docx, pdf"),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db_session),
):
    """
    Endpoint de download seguro de relatórios (SPEC §10.3, §11, §13.1 item 8).
    - O caminho do arquivo é estritamente resolvido a partir do banco de dados (previne path traversal).
    - Se o relatório pertencer a outro usuário, retorna 404 (nunca 403).
    - Entrega o arquivo com cabeçalho attachment e media_type correspondente.
    """
    report = db.execute(select(Report).where(Report.id == id)).scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório não encontrado",
        )

    # Validação de isolamento por tenant: usuário B não baixa relatório do usuário A
    project = repository.get_project_for_user(db, report.project_id, user_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório não encontrado",
        )

    if report.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"O relatório está com status '{report.status}' e ainda não pode ser baixado",
        )

    files_map = report.files_json or {}
    raw_path = files_map.get(format)
    if not raw_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"O formato '{format}' não foi gerado para este relatório",
        )

    file_path = Path(raw_path)
    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo não encontrado no servidor de armazenamento",
        )

    media_types = {
        "html": "text/html; charset=utf-8",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
    }
    media_type = media_types.get(format, "application/octet-stream")
    filename = f"relatorio_{report.type}_{report.id[:8]}.{format}"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=filename,
    )
