"""
Coletor de dados do Trello — versão multiusuário.

Recebe o `token` do usuário logado (obtido no fluxo /auth/trello/token)
em vez de um TRELLO_TOKEN fixo no .env. A `key` do app continua sendo
a mesma pra todo mundo (é pública, identifica o COGNIS como aplicação).

IDs usados no grafo:
  - Board:   "trello-board-{id}"
  - Sprint:  "trello-list-{id}"
  - Task:    "trello-card-{id}"
"""
from __future__ import annotations

import requests

from config import trello_oauth
from neo4j_writer import Neo4jWriter


def _get(token: str, path: str, **params) -> list | dict:
    resp = requests.get(
        f"{trello_oauth.api_url}{path}",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_authenticated_member(token: str) -> dict:
    """Valida o token e retorna {username, fullName, avatarUrl} — usado no /auth/trello/token."""
    return _get(token, "/members/me", fields="username,fullName,avatarUrl")


def fetch_user_boards(token: str) -> list[dict]:
    """Boards do usuário logado — pra ele escolher quais sincronizar na UI."""
    boards = _get(token, "/members/me/boards", fields="name,closed")
    return [{"id": b["id"], "name": b["name"]} for b in boards if not b.get("closed")]


def collect_board(token: str, board_id: str, writer: Neo4jWriter) -> None:
    print(f"[trello] coletando board {board_id}...")
    board = _get(token, f"/boards/{board_id}", fields="name")
    graph_board_id = f"trello-board-{board_id}"
    writer.upsert_board(board_id=graph_board_id, name=board["name"])

    _collect_members(token, board_id, writer)
    list_id_map = _collect_lists(token, board_id, graph_board_id, writer)
    _collect_cards(token, board_id, list_id_map, writer)


def _collect_members(token: str, board_id: str, writer: Neo4jWriter) -> None:
    members = _get(token, f"/boards/{board_id}/members", fields="username,fullName,avatarUrl")
    for m in members:
        writer.upsert_developer(username=m["username"], name=m.get("fullName"),
                                 avatar_url=m.get("avatarUrl"), source="trello")
    print(f"[trello]   {len(members)} membros")


def _collect_lists(token: str, board_id: str, graph_board_id: str, writer: Neo4jWriter) -> dict[str, str]:
    lists = _get(token, f"/boards/{board_id}/lists", fields="name")
    id_map = {}
    for lst in lists:
        graph_sprint_id = f"trello-list-{lst['id']}"
        writer.upsert_sprint(sprint_id=graph_sprint_id, name=lst["name"], board_id=graph_board_id)
        id_map[lst["id"]] = graph_sprint_id
    print(f"[trello]   {len(lists)} listas (sprints)")
    return id_map


def _collect_cards(token: str, board_id: str, list_id_map: dict[str, str], writer: Neo4jWriter) -> None:
    cards = _get(token, f"/boards/{board_id}/cards", fields="name,idList,url,closed",
                 members="true", member_fields="username")
    for card in cards:
        task_id = f"trello-card-{card['id']}"
        members = card.get("members", [])
        assignee_username = members[0]["username"] if members else None
        status = "closed" if card.get("closed") else "open"

        writer.upsert_task(task_id=task_id, title=card["name"], status=status,
                            url=card.get("url"), source="trello", assignee_username=assignee_username)

        for m in members:
            writer.upsert_developer(username=m["username"], source="trello")
            writer.upsert_task(task_id=task_id, title=card["name"], status=status,
                                url=card.get("url"), source="trello", assignee_username=m["username"])

        sprint_id = list_id_map.get(card["idList"])
        if sprint_id:
            writer.link_task_to_sprint(task_id=task_id, sprint_id=sprint_id)
    print(f"[trello]   {len(cards)} cards")
