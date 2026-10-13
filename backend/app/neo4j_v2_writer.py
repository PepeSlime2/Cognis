from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any

from neo4j import Driver

from .db.graph_schema import GRAPH_LABELS

MAX_BATCH_SIZE = 500

RELATIONSHIP_TYPES = frozenset(
    {
        "TEM_CONTA",
        "REALIZOU",
        "NO_REPOSITORIO",
        "ALTEROU",
        "MESCLOU",
        "ABRIU",
        "ENVIOU",
        "SOBRE",
        "COMENTOU",
        "FECHA",
        "CRIOU",
        "RESPONSAVEL_POR",
        "NA_COLUNA",
        "NO_QUADRO",
        "BLOQUEADA_POR",
        "RELACIONADA_A",
    }
)


def make_uid(project_id: str, kind: str, provider: str, external_id: str) -> str:
    parts = (project_id, kind, provider, external_id)
    if any(not part or "|" in part for part in parts):
        raise ValueError("Componentes do uid devem ser preenchidos e não conter '|'.")
    return "|".join(parts)


def _chunks(values: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    for offset in range(0, len(values), MAX_BATCH_SIZE):
        yield values[offset : offset + MAX_BATCH_SIZE]


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datas do grafo devem incluir fuso horário.")
        return value.astimezone(dt.timezone.utc)
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_value(item) for item in value)
    return value


class Neo4jV2Writer:
    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def upsert_nodes(
        self,
        project_id: str,
        label: str,
        rows: Iterable[dict[str, Any]],
    ) -> int:
        self._validate_label(label)
        prepared = [
            self._prepare_node(project_id, row)
            for row in rows
        ]
        if not prepared:
            return 0

        query = (
            f"UNWIND $rows AS row "
            f"MERGE (n:`{label}` {{uid: row.uid}}) "
            "SET n += row.properties "
            "RETURN count(n) AS written"
        )
        return sum(
            self._write_batch(query, batch, project_id)
            for batch in _chunks(prepared)
        )

    def upsert_relationships(
        self,
        project_id: str,
        source_label: str,
        relationship_type: str,
        target_label: str,
        rows: Iterable[dict[str, Any]],
    ) -> int:
        self._validate_label(source_label)
        self._validate_label(target_label)
        if relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError(f"Tipo de relação não permitido: {relationship_type}")

        prepared = [
            self._prepare_relationship(project_id, row)
            for row in rows
        ]
        if not prepared:
            return 0

        query = (
            "UNWIND $rows AS row "
            f"MATCH (source:`{source_label}` "
            "{uid: row.source_uid, project_id: $project_id}) "
            f"MATCH (target:`{target_label}` "
            "{uid: row.target_uid, project_id: $project_id}) "
            f"MERGE (source)-[relationship:`{relationship_type}`]->(target) "
            "SET relationship += row.properties "
            "RETURN count(relationship) AS written"
        )
        written = sum(
            self._write_batch(query, batch, project_id)
            for batch in _chunks(prepared)
        )
        if written != len(prepared):
            raise ValueError(
                "Uma ou mais relações não foram gravadas: nós ausentes ou fora do projeto."
            )
        return written

    def upsert_relationships_if_present(
        self,
        project_id: str,
        source_label: str,
        relationship_type: str,
        target_label: str,
        rows: Iterable[dict[str, Any]],
    ) -> tuple[int, int]:
        self._validate_label(source_label)
        self._validate_label(target_label)
        if relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError(f"Tipo de relação não permitido: {relationship_type}")

        prepared = [
            self._prepare_relationship(project_id, row)
            for row in rows
        ]
        if not prepared:
            return 0, 0

        query = (
            "UNWIND $rows AS row "
            f"OPTIONAL MATCH (source:`{source_label}` "
            "{uid: row.source_uid, project_id: $project_id}) "
            f"OPTIONAL MATCH (target:`{target_label}` "
            "{uid: row.target_uid, project_id: $project_id}) "
            "WITH row, source, target "
            "WHERE source IS NOT NULL AND target IS NOT NULL "
            f"MERGE (source)-[relationship:`{relationship_type}`]->(target) "
            "SET relationship += row.properties "
            "RETURN count(relationship) AS written"
        )
        written = sum(
            self._write_batch(query, batch, project_id)
            for batch in _chunks(prepared)
        )
        return written, len(prepared) - written

    @staticmethod
    def _validate_label(label: str) -> None:
        if label not in GRAPH_LABELS:
            raise ValueError(f"Label de nó não permitido: {label}")

    @staticmethod
    def _prepare_node(
        project_id: str, row: dict[str, Any]
    ) -> dict[str, Any]:
        uid = row.get("uid")
        if row.get("project_id") != project_id:
            raise ValueError("Todos os nós devem pertencer ao projeto informado.")
        if not Neo4jV2Writer._uid_belongs_to_project(uid, project_id):
            raise ValueError("O uid do nó deve incluir o project_id.")
        properties = {
            key: _normalize_value(value)
            for key, value in row.items()
            if key not in {"uid", "project_id"}
        }
        properties["project_id"] = project_id
        return {"uid": uid, "properties": properties}

    @staticmethod
    def _prepare_relationship(
        project_id: str, row: dict[str, Any]
    ) -> dict[str, Any]:
        source_uid = row.get("source_uid")
        target_uid = row.get("target_uid")
        if (
            not Neo4jV2Writer._uid_belongs_to_project(source_uid, project_id)
            or not Neo4jV2Writer._uid_belongs_to_project(target_uid, project_id)
        ):
            raise ValueError("As extremidades da relação devem pertencer ao projeto.")
        properties = row.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("As propriedades da relação devem ser um objeto.")
        return {
            "source_uid": source_uid,
            "target_uid": target_uid,
            "properties": _normalize_value(properties),
        }

    @staticmethod
    def _uid_belongs_to_project(uid: Any, project_id: str) -> bool:
        if not isinstance(uid, str):
            return False
        parts = uid.split("|", 3)
        return (
            len(parts) == 4
            and parts[0] == project_id
            and all(parts)
            and "|" not in parts[3]
        )

    def _write_batch(
        self,
        query: str,
        rows: list[dict[str, Any]],
        project_id: str,
    ) -> int:
        with self._driver.session() as session:
            return session.execute_write(
                self._write_transaction,
                query,
                rows,
                project_id,
            )

    @staticmethod
    def _write_transaction(
        transaction: Any,
        query: str,
        rows: list[dict[str, Any]],
        project_id: str,
    ) -> int:
        result = transaction.run(query, rows=rows, project_id=project_id)
        record = result.single(strict=True)
        return record["written"]
