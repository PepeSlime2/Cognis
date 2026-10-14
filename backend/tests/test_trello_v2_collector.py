from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from app import trello_v2_collector as collector
from app.neo4j_v2_writer import make_uid

UTC = dt.timezone.utc
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "trello" / "capture.json"


def test_classify_column():
    assert collector.classify_column("Concluído") == "done"
    assert collector.classify_column("Done") == "done"
    assert collector.classify_column("Finalizados") == "done"
    assert collector.classify_column("Entregue") == "done"

    assert collector.classify_column("Code Review") == "review"
    assert collector.classify_column("Revisão de Código") == "review"
    assert collector.classify_column("QA / Testes") == "review"

    assert collector.classify_column("Doing") == "doing"
    assert collector.classify_column("Em Andamento") == "doing"
    assert collector.classify_column("In Progress") == "doing"
    assert collector.classify_column("Desenvolvimento") == "doing"

    assert collector.classify_column("Backlog") == "backlog"

    assert collector.classify_column("A Fazer") == "todo"
    assert collector.classify_column("To Do") == "todo"
    assert collector.classify_column("Sprint") == "todo"
    assert collector.classify_column("Planejamento") == "todo"
    assert collector.classify_column("Sprint Backlog") == "backlog"

    # Default desconhecido
    assert collector.classify_column("Ideias Gerais") == "todo"


def test_parse_card_created_at_prefers_action_then_hex_id():
    card = {"id": "60c72b2f9b1d8b2e1a3f5c93"}  # 60c72b2f hex = 1623665455 unix timestamp
    actions = [
        {
            "type": "createCard",
            "date": "2026-10-10T14:30:00.000Z",
        }
    ]

    action_created_at = collector.parse_card_created_at(card, actions)
    assert action_created_at == dt.datetime(2026, 10, 10, 14, 30, tzinfo=UTC)

    # Sem ação: deriva do hex
    hex_created_at = collector.parse_card_created_at(card, [])
    expected_hex_ts = dt.datetime.fromtimestamp(int("60c72b2f", 16), tz=UTC)
    assert hex_created_at == expected_hex_ts


def test_parse_card_transitions_started_at_and_done_at():
    card = {
        "id": "card-1",
        "idList": "list-done",
        "dueComplete": False,
    }
    list_category_map = {
        "list-todo": "todo",
        "list-doing": "doing",
        "list-done": "done",
    }
    actions = [
        {
            "type": "updateCard",
            "date": "2026-10-11T10:00:00Z",
            "data": {
                "listBefore": {"id": "list-todo", "name": "A Fazer"},
                "listAfter": {"id": "list-doing", "name": "Em Andamento"},
            },
            "memberCreator": {"username": "dev1"},
        },
        {
            "type": "updateCard",
            "date": "2026-10-12T15:00:00Z",
            "data": {
                "listBefore": {"id": "list-doing", "name": "Em Andamento"},
                "listAfter": {"id": "list-done", "name": "Concluído"},
            },
            "memberCreator": {"username": "dev1"},
        },
    ]

    transitions_json, started_at, done_at = collector.parse_card_transitions(
        card, actions, list_category_map, current_category="done"
    )

    transitions = json.loads(transitions_json)
    assert len(transitions) == 2
    assert transitions[0]["from_cat"] == "todo"
    assert transitions[0]["to_cat"] == "doing"
    assert transitions[0]["by"] == "dev1"
    assert transitions[1]["to_cat"] == "done"

    assert started_at == dt.datetime(2026, 10, 11, 10, 0, tzinfo=UTC)
    assert done_at == dt.datetime(2026, 10, 12, 15, 0, tzinfo=UTC)


def test_done_at_is_none_if_current_category_is_not_done():
    card = {
        "id": "card-reopened",
        "idList": "list-doing",
    }
    list_category_map = {
        "list-doing": "doing",
        "list-done": "done",
    }
    actions = [
        {
            "type": "updateCard",
            "date": "2026-10-11T10:00:00Z",
            "data": {
                "listBefore": {"id": "list-doing", "name": "Em Andamento"},
                "listAfter": {"id": "list-done", "name": "Concluído"},
            },
        },
        {
            "type": "updateCard",
            "date": "2026-10-12T09:00:00Z",
            "data": {
                "listBefore": {"id": "list-done", "name": "Concluído"},
                "listAfter": {"id": "list-doing", "name": "Em Andamento"},
            },
        },
    ]

    _, started_at, done_at = collector.parse_card_transitions(
        card, actions, list_category_map, current_category="doing"
    )
    # Como o card retornou para doing, done_at deve ser None (sem datas inventadas)
    assert done_at is None


def test_card_without_actions_has_no_invented_dates():
    card = {
        "id": "60c72b2f9b1d8b2e1a3f5c93",
        "idList": "list-todo",
    }
    list_category_map = {"list-todo": "todo"}

    transitions_json, started_at, done_at = collector.parse_card_transitions(
        card, [], list_category_map, current_category="todo"
    )
    assert transitions_json == "[]"
    assert started_at is None
    assert done_at is None


def test_is_card_blocked():
    blocked_card = {"labels": [{"name": "Bloqueado"}], "idLabels": []}
    assert collector.is_card_blocked(blocked_card) is True

    blocked_en_card = {"labels": [{"name": "BLOCKED by dependencies"}], "idLabels": []}
    assert collector.is_card_blocked(blocked_en_card) is True

    normal_card = {"labels": [{"name": "Frontend"}, {"name": "Bug"}], "idLabels": []}
    assert collector.is_card_blocked(normal_card) is False

    id_blocked_card = {"labels": [], "idLabels": ["lbl-1"]}
    assert collector.is_card_blocked(id_blocked_card, {"lbl-1": "Bloqueado"}) is True


def test_transform_trello_board_payload_with_real_fixture():
    raw_fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    project_id = "test-proj-123"

    transformed = collector.transform_trello_board_payload(raw_fixture, project_id)

    nodes = transformed["nodes"]
    assert len(nodes["Board"]) == 1
    board_node = nodes["Board"][0]
    assert board_node["uid"] == make_uid(project_id, "board", "trello", "60c72b2f9b1d8b2e1a3f5c90")
    assert board_node["name"] == "Sprint Board"

    columns = nodes["Column"]
    assert len(columns) == 2
    col_names = {c["name"]: c["category"] for c in columns}
    assert col_names["A Fazer"] == "todo"
    assert col_names["Concluído"] == "done"

    tasks = nodes["Task"]
    assert len(tasks) == 4
    task_jwt = next(t for t in tasks if "JWT" in t["title"])
    assert task_jwt["status_category"] == "done"

    relacionada = transformed["relacionada_links"]
    assert len(relacionada) == 2  # PR 2 e Issue 1 anexados nos cards
    pr_link = next(r for r in relacionada if r.get("target_label") == "PullRequest")
    assert pr_link["properties"]["via"] == "attachment"
    assert pr_link["properties"]["confidence"] == 1.0


def test_comment_node_stores_length_and_omits_body():
    project_id = "test-proj-comments"
    payload = {
        "board": {"id": "b1", "name": "Board"},
        "lists": [{"id": "l1", "name": "To Do"}],
        "cards": [{"id": "c1", "name": "Card 1", "idList": "l1"}],
        "actions": [
            {
                "id": "act-comment-1",
                "type": "commentCard",
                "date": "2026-10-11T12:00:00Z",
                "data": {
                    "card": {"id": "c1"},
                    "text": "Comentário confidencial da equipe de desenvolvimento",
                },
                "memberCreator": {"username": "commenter1"},
            }
        ],
    }

    transformed = collector.transform_trello_board_payload(payload, project_id)
    comments = transformed["nodes"]["Comment"]
    assert len(comments) == 1
    comment = comments[0]
    assert comment["length"] == len("Comentário confidencial da equipe de desenvolvimento")
    # Regra LGPD / SPEC: nunca salvar corpo de comentários
    assert "text" not in comment
    assert "body" not in comment
