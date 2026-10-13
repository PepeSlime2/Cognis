from __future__ import annotations

from typing import Any

from neo4j import Driver

GRAPH_LAYERS = {
    "all": ("Account", "Task", "PullRequest", "Repo", "Module", "Column"),
    "people": ("Account",),
    "tasks": ("Account", "Task", "Column"),
    "artifacts": ("Account", "PullRequest", "Repo", "Module"),
}
NODE_TYPES = {
    "Account": "person",
    "Task": "task",
    "PullRequest": "pr",
    "Repo": "repo",
    "Module": "module",
    "Column": "column",
}
RELATIONSHIP_TYPES = {
    "ABRIU": "abriu",
    "MESCLOU": "mesclou",
    "FECHA": "fecha",
    "CRIOU": "criou",
    "RESPONSAVEL_POR": "responsavel",
    "NO_REPOSITORIO": "no_repositorio",
    "ALTEROU": "alterou",
    "BLOQUEADA_POR": "bloqueada_por",
    "NA_COLUNA": "na_coluna",
    "NO_QUADRO": "no_quadro",
    "REALIZOU": "realizou",
}
NODE_QUERY = """
MATCH (n)
WHERE n.project_id = $project_id
  AND labels(n)[0] IN $labels
  AND ($include_bots OR NOT coalesce(n.is_bot, false))
OPTIONAL MATCH (n)-[r]-(neighbor)
WHERE neighbor.project_id = $project_id
  AND ($include_bots OR NOT coalesce(neighbor.is_bot, false))
WITH n, sum(CASE WHEN r IS NULL THEN 0 ELSE coalesce(r.weight, 1) END) AS degree
ORDER BY degree DESC, n.uid
LIMIT $limit
RETURN labels(n) AS labels, properties(n) AS properties, degree
"""
EDGE_QUERY = """
MATCH (source)-[r]->(target)
WHERE source.project_id = $project_id
  AND target.project_id = $project_id
  AND source.uid IN $uids
  AND target.uid IN $uids
RETURN source.uid AS source, target.uid AS target,
       type(r) AS relationship, properties(r) AS properties
"""
REVIEW_EDGE_QUERY = """
MATCH (account:Account)-[:ENVIOU]->(review:Review)-[:SOBRE]->(target:PullRequest)
WHERE account.project_id = $project_id
  AND review.project_id = $project_id
  AND target.project_id = $project_id
  AND account.uid IN $uids
  AND target.uid IN $uids
RETURN account.uid AS source, target.uid AS target, count(review) AS weight
"""
COMMENT_EDGE_QUERY = """
MATCH (account:Account)-[:COMENTOU]->(comment:Comment)-[:SOBRE]->(target)
WHERE account.project_id = $project_id
  AND comment.project_id = $project_id
  AND target.project_id = $project_id
  AND account.uid IN $uids
  AND target.uid IN $uids
RETURN account.uid AS source, target.uid AS target, count(comment) AS weight
"""
COMMIT_REPO_EDGE_QUERY = """
MATCH (account:Account)-[:REALIZOU]->(commit:Commit)-[:NO_REPOSITORIO]->(repo:Repo)
WHERE account.project_id = $project_id
  AND commit.project_id = $project_id
  AND repo.project_id = $project_id
  AND account.uid IN $uids
  AND repo.uid IN $uids
RETURN account.uid AS source, repo.uid AS target, count(DISTINCT commit) AS weight
"""
COMMIT_MODULE_EDGE_QUERY = """
MATCH (account:Account)-[:REALIZOU]->(commit:Commit)-[:ALTEROU]->(module:Module)
WHERE account.project_id = $project_id
  AND commit.project_id = $project_id
  AND module.project_id = $project_id
  AND account.uid IN $uids
  AND module.uid IN $uids
RETURN account.uid AS source, module.uid AS target, count(DISTINCT commit) AS weight
"""


def build_cytoscape_elements(
    nodes: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    layer: str = "all",
    max_nodes: int = 400,
    min_weight: float = 1,
    include_bots: bool = False,
) -> dict[str, Any]:
    if layer not in GRAPH_LAYERS:
        raise ValueError("Camada de grafo inválida.")
    if not 1 <= max_nodes <= 400:
        raise ValueError("max_nodes deve estar entre 1 e 400.")
    if min_weight < 0:
        raise ValueError("min_weight não pode ser negativo.")

    allowed_labels = set(GRAPH_LAYERS[layer])
    filtered_nodes = [
        node
        for node in nodes
        if node["label"] in allowed_labels
        and (include_bots or not node["properties"].get("is_bot", False))
    ]
    filtered_nodes.sort(key=lambda node: (-node["degree"], node["properties"]["uid"]))
    truncated = len(filtered_nodes) > max_nodes
    selected_nodes = filtered_nodes[:max_nodes]
    selected_uids = {node["properties"]["uid"] for node in selected_nodes}

    edge_groups: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_edge(
        source: str,
        target: str,
        relationship_type: str,
        weight: int = 1,
        breakdown: dict[str, Any] | None = None,
    ) -> None:
        if source not in selected_uids or target not in selected_uids:
            return
        key = (source, target, relationship_type)
        edge = edge_groups.setdefault(
            key,
            {
                "source": source,
                "target": target,
                "type": relationship_type,
                "weight": 0,
                "breakdown": {},
            },
        )
        edge["weight"] += weight
        if breakdown:
            edge["breakdown"].update(breakdown)

    for relationship in relationships:
        mapped_type = RELATIONSHIP_TYPES.get(relationship["relationship"])
        if mapped_type is not None:
            add_edge(
                relationship["source"],
                relationship["target"],
                mapped_type,
                breakdown=relationship.get("properties"),
            )
        elif relationship["relationship"] in ("review", "comment"):
            add_edge(
                relationship["source"],
                relationship["target"],
                relationship["relationship"],
                relationship["weight"],
            )
        elif relationship["relationship"] == "commit_activity":
            add_edge(
                relationship["source"],
                relationship["target"],
                "alterou",
                relationship["weight"],
            )

    edge_data = [
        {
            "id": f"{source}|{relationship_type}|{target}",
            **edge,
        }
        for (source, target, relationship_type), edge in edge_groups.items()
        if edge["weight"] >= min_weight
    ]
    edge_data.sort(
        key=lambda edge: (
            -edge["weight"],
            edge["source"],
            edge["type"],
            edge["target"],
        )
    )
    edges_truncated = len(edge_data) > 1500
    edge_data = edge_data[:1500]
    max_degree = max((node["degree"] for node in selected_nodes), default=0)
    node_data = []
    for node in selected_nodes:
        label = node["label"]
        properties = node["properties"]
        display_label = (
            properties.get("display_name")
            or properties.get("login")
            or properties.get("title")
            or properties.get("message")
            or properties.get("full_name")
            or properties.get("path")
            or properties.get("name")
            or label
        )
        node_data.append(
            {
                "id": properties["uid"],
                "label": display_label,
                "type": NODE_TYPES[label],
                "size_metric": node["degree"] / max_degree if max_degree else 0,
                "community": properties.get("community"),
                "flags": ["bot"] if properties.get("is_bot") else [],
                "metrics": {},
                "status_category": properties.get("status_category"),
                "url": properties.get("url"),
            }
        )

    return {
        "elements": {
            "nodes": [{"data": node} for node in node_data],
            "edges": [{"data": edge} for edge in edge_data],
        },
        "truncated": truncated or edges_truncated,
        "stats": {
            "nodes": len(node_data),
            "edges": len(edge_data),
        },
    }


def get_project_graph(
    driver: Driver,
    project_id: str,
    layer: str = "all",
    max_nodes: int = 400,
    min_weight: float = 1,
    include_bots: bool = False,
) -> dict[str, Any]:
    if layer not in GRAPH_LAYERS:
        raise ValueError("Camada de grafo inválida.")
    if not 1 <= max_nodes <= 400:
        raise ValueError("max_nodes deve estar entre 1 e 400.")
    if min_weight < 0:
        raise ValueError("min_weight não pode ser negativo.")

    labels = GRAPH_LAYERS[layer]
    with driver.session() as session:
        node_records = list(
            session.run(
                NODE_QUERY,
                project_id=project_id,
                labels=list(labels),
                include_bots=include_bots,
                limit=max_nodes + 1,
            )
        )
        query_nodes = [
            {
                "label": record["labels"][0],
                "properties": dict(record["properties"]),
                "degree": record["degree"],
            }
            for record in node_records
        ]
        selected_nodes = query_nodes[:max_nodes]
        uids = [node["properties"]["uid"] for node in selected_nodes]
        relationships: list[dict[str, Any]] = []
        if uids:
            relationships = [
                {
                    "source": record["source"],
                    "target": record["target"],
                    "relationship": record["relationship"],
                    "properties": dict(record["properties"]),
                }
                for record in session.run(
                    EDGE_QUERY,
                    project_id=project_id,
                    uids=uids,
                )
            ]
            if "Account" in labels and (
                "PullRequest" in labels or "Task" in labels
            ):
                reviews = [
                    {
                        "source": record["source"],
                        "target": record["target"],
                        "relationship": "review",
                        "weight": record["weight"],
                        "properties": {},
                    }
                    for record in session.run(
                        REVIEW_EDGE_QUERY,
                        project_id=project_id,
                        uids=uids,
                    )
                ]
                comments = [
                    {
                        "source": record["source"],
                        "target": record["target"],
                        "relationship": "comment",
                        "weight": record["weight"],
                        "properties": {},
                    }
                    for record in session.run(
                        COMMENT_EDGE_QUERY,
                        project_id=project_id,
                        uids=uids,
                    )
                ]
                relationships.extend(reviews)
                relationships.extend(comments)
            if "Account" in labels and "Repo" in labels:
                relationships.extend(
                    {
                        "source": record["source"],
                        "target": record["target"],
                        "relationship": "commit_activity",
                        "weight": record["weight"],
                        "properties": {},
                    }
                    for record in session.run(
                        COMMIT_REPO_EDGE_QUERY,
                        project_id=project_id,
                        uids=uids,
                    )
                )
            if "Account" in labels and "Module" in labels:
                relationships.extend(
                    {
                        "source": record["source"],
                        "target": record["target"],
                        "relationship": "commit_activity",
                        "weight": record["weight"],
                        "properties": {},
                    }
                    for record in session.run(
                        COMMIT_MODULE_EDGE_QUERY,
                        project_id=project_id,
                        uids=uids,
                    )
                )

    result = build_cytoscape_elements(
        query_nodes,
        relationships,
        layer,
        max_nodes,
        min_weight,
        include_bots,
    )
    result["truncated"] = result["truncated"] or len(node_records) > max_nodes
    return result
