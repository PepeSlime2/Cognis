from contextlib import contextmanager

from app.graph_service import build_cytoscape_elements, get_project_graph


def test_build_graph_filters_bots_aggregates_activities_and_caps_nodes():
    nodes = [
        {
            "label": "Account",
            "properties": {"uid": "person-1", "display_name": "Alice", "is_bot": False},
            "degree": 5,
        },
        {
            "label": "PullRequest",
            "properties": {"uid": "pr-1", "title": "Improve graph"},
            "degree": 3,
        },
        {
            "label": "Repo",
            "properties": {"uid": "repo-1", "full_name": "owner/repo"},
            "degree": 1,
        },
        {
            "label": "Account",
            "properties": {"uid": "bot-1", "login": "dependabot[bot]", "is_bot": True},
            "degree": 8,
        },
    ]
    relationships = [
        {
            "source": "person-1",
            "target": "pr-1",
            "relationship": "ABRIU",
            "properties": {},
        },
        {
            "source": "person-1",
            "target": "pr-1",
            "relationship": "review",
            "weight": 2,
            "properties": {},
        },
        {
            "source": "person-1",
            "target": "pr-1",
            "relationship": "comment",
            "weight": 3,
            "properties": {},
        },
    ]

    result = build_cytoscape_elements(
        nodes,
        relationships,
        layer="artifacts",
        max_nodes=2,
        min_weight=2,
    )

    assert result["truncated"] is True
    assert {item["data"]["id"] for item in result["elements"]["nodes"]} == {
        "person-1",
        "pr-1",
    }
    assert {
        (item["data"]["type"], item["data"]["weight"])
        for item in result["elements"]["edges"]
    } == {("review", 2), ("comment", 3)}


class RecordingGraphSession:
    def __init__(self):
        self.calls = []

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        if "RETURN labels(n)" in query:
            return [
                {
                    "labels": ["Account"],
                    "properties": {
                        "uid": "person-1",
                        "login": "alice",
                        "is_bot": False,
                    },
                    "degree": 3,
                },
                {
                    "labels": ["PullRequest"],
                    "properties": {"uid": "pr-1", "title": "Graph API"},
                    "degree": 2,
                },
                {
                    "labels": ["Repo"],
                    "properties": {"uid": "repo-1", "full_name": "owner/repo"},
                    "degree": 2,
                },
                {
                    "labels": ["Module"],
                    "properties": {"uid": "module-1", "path": "backend/app"},
                    "degree": 1,
                },
            ]
        if "type(r) AS relationship" in query:
            return [
                {
                    "source": "person-1",
                    "target": "pr-1",
                    "relationship": "ABRIU",
                    "properties": {},
                }
            ]
        if ":Review" in query:
            return [{"source": "person-1", "target": "pr-1", "weight": 2}]
        if ":Comment" in query:
            return [{"source": "person-1", "target": "pr-1", "weight": 1}]
        if "NO_REPOSITORIO" in query:
            return [{"source": "person-1", "target": "repo-1", "weight": 3}]
        if "REALIZOU" in query and "ALTEROU" in query:
            return [{"source": "person-1", "target": "module-1", "weight": 2}]
        return []


class RecordingGraphDriver:
    def __init__(self):
        self.graph_session = RecordingGraphSession()

    @contextmanager
    def session(self):
        yield self.graph_session


def test_every_graph_query_is_project_scoped_and_activities_are_collapsed():
    driver = RecordingGraphDriver()

    result = get_project_graph(driver, "project-1")

    assert {edge["data"]["type"] for edge in result["elements"]["edges"]} == {
        "abriu",
        "review",
        "comment",
        "alterou",
    }
    assert {node["data"]["type"] for node in result["elements"]["nodes"]} == {
        "person",
        "pr",
        "repo",
        "module",
    }
    assert {
        edge["data"]["weight"]
        for edge in result["elements"]["edges"]
        if edge["data"]["type"] == "alterou"
    } == {2, 3}
    assert all(
        parameters["project_id"] == "project-1"
        for _, parameters in driver.graph_session.calls
    )
    assert "n.project_id = $project_id" in driver.graph_session.calls[0][0]
    assert "source.project_id = $project_id" in driver.graph_session.calls[1][0]
    assert "target.project_id = $project_id" in driver.graph_session.calls[1][0]
    assert all(
        "project_id = $project_id" in query
        for query, _ in driver.graph_session.calls[2:]
    )
