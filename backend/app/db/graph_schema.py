from neo4j import Driver


GRAPH_LABELS = (
    "Person",
    "Account",
    "Repo",
    "Module",
    "Commit",
    "PullRequest",
    "Review",
    "Comment",
    "Task",
    "Column",
    "Board",
)


def ensure_graph_schema(driver: Driver) -> None:
    with driver.session() as session:
        for label in GRAPH_LABELS:
            schema_name = label.lower()
            session.run(
                f"CREATE CONSTRAINT {schema_name}_uid IF NOT EXISTS "
                f"FOR (n:`{label}`) REQUIRE n.uid IS UNIQUE"
            ).consume()
            session.run(
                f"CREATE INDEX {schema_name}_project IF NOT EXISTS "
                f"FOR (n:`{label}`) ON (n.project_id)"
            ).consume()
