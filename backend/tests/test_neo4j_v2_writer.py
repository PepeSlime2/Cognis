import datetime as dt

import pytest

from app.db.graph_schema import GRAPH_LABELS, ensure_graph_schema
from app.neo4j_v2_writer import MAX_BATCH_SIZE, Neo4jV2Writer, make_uid


class FakeRecord(dict):
    pass


class FakeResult:
    def __init__(self, written):
        self.written = written

    def single(self, strict=False):
        return FakeRecord(written=self.written)

    def consume(self):
        return None


class FakeTransaction:
    def __init__(self, calls):
        self.calls = calls

    def run(self, query, **params):
        self.calls.append((query, params))
        return FakeResult(len(params["rows"]))


class FakeSession:
    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute_write(self, callback, *args):
        return callback(FakeTransaction(self.calls), *args)

    def run(self, query):
        self.calls.append((query, {}))
        return FakeResult(0)


class FakeDriver:
    def __init__(self):
        self.calls = []

    def session(self):
        return FakeSession(self.calls)


def test_schema_creation_is_idempotent_and_covers_all_v2_labels():
    driver = FakeDriver()

    ensure_graph_schema(driver)
    first_run = [query for query, _ in driver.calls]
    ensure_graph_schema(driver)
    second_run = [query for query, _ in driver.calls[len(first_run) :]]

    assert len(GRAPH_LABELS) == 11
    assert len(first_run) == len(GRAPH_LABELS) * 2
    assert second_run == first_run
    assert all("IF NOT EXISTS" in query for query in first_run)
    assert all("REQUIRE n.uid IS UNIQUE" in first_run[index] for index in range(0, len(first_run), 2))
    assert all("n.project_id" in first_run[index] for index in range(1, len(first_run), 2))


def test_node_batches_use_project_scoped_merge_and_native_utc_dates():
    driver = FakeDriver()
    writer = Neo4jV2Writer(driver)
    project_id = "project-a"
    local_time = dt.datetime(
        2026, 1, 1, 12, tzinfo=dt.timezone(dt.timedelta(hours=-3))
    )
    rows = [
        {
            "uid": make_uid(project_id, "commit", "github", f"sha-{index}"),
            "project_id": project_id,
            "authored_at": local_time,
        }
        for index in range(MAX_BATCH_SIZE + 1)
    ]

    assert writer.upsert_nodes(project_id, "Commit", rows) == MAX_BATCH_SIZE + 1
    assert len(driver.calls) == 2
    query, params = driver.calls[0]
    assert "UNWIND $rows AS row" in query
    assert "MERGE (n:`Commit` {uid: row.uid})" in query
    assert params["rows"][0]["properties"]["project_id"] == project_id
    assert params["rows"][0]["properties"]["authored_at"] == dt.datetime(
        2026, 1, 1, 15, tzinfo=dt.timezone.utc
    )
    assert params["rows"][0]["properties"]["project_id"] == project_id


def test_node_writer_rejects_cross_project_and_naive_datetimes():
    writer = Neo4jV2Writer(FakeDriver())

    with pytest.raises(ValueError, match="pertencer"):
        writer.upsert_nodes(
            "project-a",
            "Task",
            [{"uid": "project-b|task|github|repo#1", "project_id": "project-b"}],
        )

    with pytest.raises(ValueError, match="uid"):
        writer.upsert_nodes(
            "project-a",
            "Task",
            [{"uid": "project-a|task", "project_id": "project-a"}],
        )

    with pytest.raises(ValueError, match="fuso horário"):
        writer.upsert_nodes(
            "project-a",
            "Task",
            [
                {
                    "uid": make_uid("project-a", "task", "github", "repo#1"),
                    "project_id": "project-a",
                    "created_at": dt.datetime(2026, 1, 1),
                }
            ],
        )


def test_make_uid_rejects_empty_or_ambiguous_components():
    with pytest.raises(ValueError, match="uid"):
        make_uid("project-a", "task", "github", "")

    with pytest.raises(ValueError, match="uid"):
        make_uid("project-a", "task|other", "github", "repo#1")


def test_relationship_writer_requires_project_endpoints_and_is_idempotent_merge():
    driver = FakeDriver()
    writer = Neo4jV2Writer(driver)
    project_id = "project-a"
    rows = [
        {
            "source_uid": make_uid(project_id, "account", "github", "user-a"),
            "target_uid": make_uid(project_id, "commit", "github", "sha-1"),
            "properties": {},
        }
    ]

    assert writer.upsert_relationships(
        project_id, "Account", "REALIZOU", "Commit", rows
    ) == 1
    query, params = driver.calls[0]
    assert "project_id: $project_id" in query
    assert "MERGE (source)-[relationship:`REALIZOU`]->(target)" in query
    assert params["project_id"] == project_id

    with pytest.raises(ValueError, match="pertencer"):
        writer.upsert_relationships(
            project_id,
            "Account",
            "REALIZOU",
            "Commit",
            [{**rows[0], "target_uid": "project-b|commit|github|sha-1"}],
        )
