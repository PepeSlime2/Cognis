from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import trello_oauth
from .db.models import ColumnMapping, ProjectSource, utc_now
from .linker import parse_trello_attachments
from .neo4j_v2_writer import Neo4jV2Writer, make_uid
from .trello_tokens import (
    TrelloReconnectRequired,
    TrelloTokenRefreshError,
    refresh_if_needed,
)

BLOCKED_RE = re.compile(r"bloquead|blocked", re.IGNORECASE)


def parse_iso_datetime(value: str | None) -> dt.datetime | None:
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def classify_column(name: str) -> str:
    lowered = name.strip().lower()
    if re.search(r"done|conclu|feito|finaliz|entregue", lowered):
        return "done"
    if re.search(r"review|revis|code review|qa|teste", lowered):
        return "review"
    if re.search(r"doing|andamento|progress|fazendo|desenvolv", lowered):
        return "doing"
    if re.search(r"backlog", lowered):
        return "backlog"
    if re.search(r"todo|to do|a fazer|sprint|planej", lowered):
        return "todo"
    return "todo"


def parse_card_created_at(
    card: dict[str, Any],
    card_actions: list[dict[str, Any]] | None = None,
) -> dt.datetime:
    if card_actions:
        for action in card_actions:
            if action.get("type") == "createCard" and action.get("date"):
                parsed = parse_iso_datetime(action["date"])
                if parsed is not None:
                    return parsed

    card_id = card.get("id", "")
    if len(card_id) >= 8:
        try:
            timestamp = int(card_id[:8], 16)
            return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
        except ValueError:
            pass

    return utc_now()


def parse_card_transitions(
    card: dict[str, Any],
    card_actions: list[dict[str, Any]],
    list_category_map: dict[str, str],
    current_category: str,
) -> tuple[str, dt.datetime | None, dt.datetime | None]:
    update_actions: list[dict[str, Any]] = []
    due_complete_action_date: dt.datetime | None = None

    for action in card_actions:
        act_type = action.get("type")
        act_data = action.get("data", {})
        if act_type == "updateCard":
            if "listBefore" in act_data and "listAfter" in act_data:
                action_date = parse_iso_datetime(action.get("date"))
                if action_date is not None:
                    update_actions.append(action)
            card_data = act_data.get("card", {})
            if card_data.get("dueComplete") is True:
                parsed_due_date = parse_iso_datetime(action.get("date"))
                if parsed_due_date is not None:
                    due_complete_action_date = parsed_due_date

    update_actions.sort(key=lambda a: parse_iso_datetime(a.get("date")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc))

    transitions: list[dict[str, Any]] = []
    for action in update_actions:
        action_date = parse_iso_datetime(action.get("date"))
        if action_date is None:
            continue
        act_data = action.get("data", {})
        list_before = act_data.get("listBefore", {})
        list_after = act_data.get("listAfter", {})

        from_cat = list_category_map.get(
            list_before.get("id"),
            classify_column(list_before.get("name", "")),
        )
        to_cat = list_category_map.get(
            list_after.get("id"),
            classify_column(list_after.get("name", "")),
        )
        by_user = action.get("memberCreator", {}).get("username")

        transitions.append(
            {
                "at": action_date.isoformat(),
                "from_cat": from_cat,
                "to_cat": to_cat,
                "by": by_user,
            }
        )

    transitions_json = json.dumps(transitions, ensure_ascii=False)

    started_at: dt.datetime | None = None
    for trans in transitions:
        if trans["to_cat"] == "doing":
            started_at = parse_iso_datetime(trans["at"])
            break

    done_at: dt.datetime | None = None
    if current_category == "done":
        for trans in reversed(transitions):
            if trans["to_cat"] == "done":
                done_at = parse_iso_datetime(trans["at"])
                break
        if done_at is None and card.get("dueComplete") is True:
            done_at = due_complete_action_date

    return transitions_json, started_at, done_at


def is_card_blocked(
    card: dict[str, Any],
    board_labels_map: dict[str, str] | None = None,
) -> bool:
    labels = card.get("labels")
    if isinstance(labels, list):
        for label in labels:
            if isinstance(label, dict):
                label_name = label.get("name") or ""
                if BLOCKED_RE.search(label_name):
                    return True
            elif isinstance(label, str) and BLOCKED_RE.search(label):
                return True

    id_labels = card.get("idLabels")
    if isinstance(id_labels, list) and board_labels_map:
        for label_id in id_labels:
            label_name = board_labels_map.get(label_id, "")
            if BLOCKED_RE.search(label_name):
                return True

    return False


def extract_card_labels(
    card: dict[str, Any],
    board_labels_map: dict[str, str] | None = None,
) -> list[str]:
    names: list[str] = []
    labels = card.get("labels")
    if isinstance(labels, list):
        for label in labels:
            if isinstance(label, dict):
                name = (label.get("name") or "").strip()
                if name and name not in names:
                    names.append(name)
            elif isinstance(label, str):
                name = label.strip()
                if name and name not in names:
                    names.append(name)

    id_labels = card.get("idLabels")
    if isinstance(id_labels, list) and board_labels_map:
        for label_id in id_labels:
            name = board_labels_map.get(label_id, "").strip()
            if name and name not in names:
                names.append(name)

    return names


def _trello_get(token: str, path: str, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(
        f"{trello_oauth.api_url}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )
    if response.status_code == 403 and "outside authorized workspace" in response.text:
        raise ValueError(
            "O quadro está fora da Área de Trabalho autorizada pelo Trello. "
            "Reconecte o Trello para autorizar a Área de Trabalho deste quadro."
        )
    response.raise_for_status()
    return response.json()


def fetch_board_data(token: str, board_id: str) -> dict[str, Any]:
    encoded_id = quote(board_id, safe="")
    board = _trello_get(token, f"/boards/{encoded_id}", params={"fields": "name,url,shortLink"})
    members = _trello_get(
        token,
        f"/boards/{encoded_id}/members",
        params={"fields": "username,fullName,avatarUrl"},
    )
    lists = _trello_get(
        token,
        f"/boards/{encoded_id}/lists",
        params={"filter": "all", "fields": "name,closed,pos"},
    )
    cards = _trello_get(
        token,
        f"/boards/{encoded_id}/cards",
        params={
            "filter": "all",
            "fields": "name,idList,idMembers,url,shortLink,closed,due,dueComplete,dateLastActivity,idLabels",
            "attachments": "true",
            "members": "true",
            "member_fields": "username",
        },
    )

    try:
        labels = _trello_get(
            token,
            f"/boards/{encoded_id}/labels",
            params={"fields": "name,color"},
        )
    except requests.RequestException:
        labels = []

    actions: list[dict[str, Any]] = []
    before: str | None = None
    for _ in range(5):
        params: dict[str, Any] = {
            "filter": "createCard,updateCard:idList,updateCard:closed,updateCard:dueComplete,commentCard",
            "limit": 1000,
        }
        if before:
            params["before"] = before
        try:
            batch = _trello_get(token, f"/boards/{encoded_id}/actions", params=params)
        except requests.RequestException:
            break
        if not isinstance(batch, list) or not batch:
            break
        actions.extend(batch)
        if len(batch) < 1000:
            break
        before = batch[-1].get("id")

    return {
        "board": board,
        "members": members,
        "lists": lists,
        "cards": cards,
        "labels": labels,
        "actions": actions,
    }


def transform_trello_board_payload(
    payload: dict[str, Any],
    project_id: str,
    existing_column_categories: dict[str, str] | None = None,
) -> dict[str, Any]:
    board_data = payload.get("board") or {}
    board_id = board_data.get("id") or "unknown_board"
    board_name = board_data.get("name") or "Quadro Trello"
    board_url = board_data.get("url") or f"https://trello.com/b/{board_id}"
    board_uid = make_uid(project_id, "board", "trello", board_id)

    board_node = {
        "uid": board_uid,
        "project_id": project_id,
        "name": board_name,
        "url": board_url,
    }

    board_labels_map: dict[str, str] = {}
    for label in payload.get("labels") or []:
        if isinstance(label, dict) and label.get("id"):
            board_labels_map[label["id"]] = label.get("name") or ""

    members_by_id: dict[str, str] = {}
    members_by_username: dict[str, dict[str, Any]] = {}
    for member in payload.get("members") or []:
        if isinstance(member, dict) and member.get("username"):
            uname = member["username"]
            members_by_username[uname] = member
            if member.get("id"):
                members_by_id[member["id"]] = uname

    actions = payload.get("actions") or []
    actions_by_card: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        if not isinstance(action, dict):
            continue
        creator = action.get("memberCreator")
        if isinstance(creator, dict) and creator.get("username"):
            uname = creator["username"]
            if uname not in members_by_username:
                members_by_username[uname] = creator
            if creator.get("id"):
                members_by_id[creator["id"]] = uname

        card_ref = action.get("data", {}).get("card", {})
        cid = card_ref.get("id")
        if cid:
            actions_by_card.setdefault(cid, []).append(action)

    account_nodes: list[dict[str, Any]] = []
    for uname, info in members_by_username.items():
        account_nodes.append(
            {
                "uid": make_uid(project_id, "account", "trello", uname),
                "project_id": project_id,
                "provider": "trello",
                "login": uname,
                "display_name": info.get("fullName") or uname,
                "avatar_url": info.get("avatarUrl"),
                "is_bot": False,
                "linked": False,
            }
        )

    lists = payload.get("lists") or []
    column_nodes: list[dict[str, Any]] = []
    no_quadro_column_rels: list[dict[str, Any]] = []
    list_category_map: dict[str, str] = {}
    list_uid_map: dict[str, str] = {}
    new_column_mappings: dict[str, dict[str, Any]] = {}

    for pos, lst in enumerate(lists):
        list_id = lst.get("id") or f"list_{pos}"
        list_name = lst.get("name") or f"Coluna {pos}"
        column_uid = make_uid(project_id, "column", "trello", list_id)

        category = (existing_column_categories or {}).get(column_uid)
        if not category:
            category = classify_column(list_name)
            new_column_mappings[column_uid] = {
                "name": list_name,
                "category": category,
                "source": "auto",
            }

        list_category_map[list_id] = category
        list_uid_map[list_id] = column_uid

        column_nodes.append(
            {
                "uid": column_uid,
                "project_id": project_id,
                "name": list_name,
                "position": float(lst.get("pos", pos + 1)),
                "category": category,
                "board_uid": board_uid,
            }
        )
        no_quadro_column_rels.append(
            {
                "source_uid": column_uid,
                "target_uid": board_uid,
            }
        )

    cards = payload.get("cards") or []
    task_nodes: list[dict[str, Any]] = []
    comment_nodes: list[dict[str, Any]] = []
    na_coluna_rels: list[dict[str, Any]] = []
    no_quadro_task_rels: list[dict[str, Any]] = []
    responsavel_rels: list[dict[str, Any]] = []
    criou_rels: list[dict[str, Any]] = []
    comentou_rels: list[dict[str, Any]] = []
    sobre_rels: list[dict[str, Any]] = []

    for card in cards:
        if not isinstance(card, dict) or not card.get("id"):
            continue
        cid = card["id"]
        card_actions = actions_by_card.get(cid, [])
        card_list_id = card.get("idList", "")
        current_category = list_category_map.get(card_list_id, "todo")

        created_at = parse_card_created_at(card, card_actions)
        transitions_json, started_at, done_at = parse_card_transitions(
            card,
            card_actions,
            list_category_map,
            current_category,
        )
        blocked = is_card_blocked(card, board_labels_map)
        labels = extract_card_labels(card, board_labels_map)
        due_at = parse_iso_datetime(card.get("due"))
        updated_at = parse_iso_datetime(card.get("dateLastActivity")) or created_at

        task_uid = make_uid(project_id, "task", "trello", cid)
        task_nodes.append(
            {
                "uid": task_uid,
                "project_id": project_id,
                "kind": "card",
                "provider": "trello",
                "title": card.get("name") or "Sem título",
                "status_category": current_category,
                "created_at": created_at,
                "updated_at": updated_at,
                "due_at": due_at,
                "done_at": done_at,
                "started_at": started_at,
                "blocked": blocked,
                "labels": labels,
                "transitions_json": transitions_json,
                "url": card.get("url") or f"https://trello.com/c/{cid}",
            }
        )

        col_uid = list_uid_map.get(card_list_id)
        if col_uid:
            na_coluna_rels.append(
                {
                    "source_uid": task_uid,
                    "target_uid": col_uid,
                }
            )
        no_quadro_task_rels.append(
            {
                "source_uid": task_uid,
                "target_uid": board_uid,
            }
        )

        assigned_usernames: set[str] = set()
        for member_item in card.get("members") or []:
            if isinstance(member_item, dict) and member_item.get("username"):
                assigned_usernames.add(member_item["username"])
        for mid in card.get("idMembers") or []:
            uname = members_by_id.get(mid)
            if uname:
                assigned_usernames.add(uname)

        for uname in assigned_usernames:
            account_uid = make_uid(project_id, "account", "trello", uname)
            responsavel_rels.append(
                {
                    "source_uid": account_uid,
                    "target_uid": task_uid,
                }
            )

        creator_username: str | None = None
        for action in card_actions:
            if action.get("type") == "createCard":
                creator_username = action.get("memberCreator", {}).get("username")
                break
        if creator_username:
            account_uid = make_uid(project_id, "account", "trello", creator_username)
            criou_rels.append(
                {
                    "source_uid": account_uid,
                    "target_uid": task_uid,
                }
            )

        for action in card_actions:
            if action.get("type") == "commentCard" and action.get("id"):
                action_date = parse_iso_datetime(action.get("date")) or created_at
                comment_text = action.get("data", {}).get("text", "") or ""
                comment_uid = make_uid(project_id, "comment", "trello", action["id"])

                comment_nodes.append(
                    {
                        "uid": comment_uid,
                        "project_id": project_id,
                        "created_at": action_date,
                        "length": len(comment_text),
                    }
                )
                sobre_rels.append(
                    {
                        "source_uid": comment_uid,
                        "target_uid": task_uid,
                    }
                )
                author = action.get("memberCreator", {}).get("username")
                if author:
                    account_uid = make_uid(project_id, "account", "trello", author)
                    comentou_rels.append(
                        {
                            "source_uid": account_uid,
                            "target_uid": comment_uid,
                        }
                    )

    relacionada_links = parse_trello_attachments(cards, project_id)

    return {
        "nodes": {
            "Board": [board_node],
            "Column": column_nodes,
            "Account": account_nodes,
            "Task": task_nodes,
            "Comment": comment_nodes,
        },
        "relationships": {
            ("Column", "NO_QUADRO", "Board"): no_quadro_column_rels,
            ("Task", "NA_COLUNA", "Column"): na_coluna_rels,
            ("Task", "NO_QUADRO", "Board"): no_quadro_task_rels,
            ("Account", "RESPONSAVEL_POR", "Task"): responsavel_rels,
            ("Account", "CRIOU", "Task"): criou_rels,
            ("Account", "COMENTOU", "Comment"): comentou_rels,
            ("Comment", "SOBRE", "Task"): sobre_rels,
        },
        "relacionada_links": relacionada_links,
        "new_column_mappings": new_column_mappings,
    }


def sync_trello_project(
    session: Session,
    user_id: str,
    project_id: str,
    writer: Neo4jV2Writer,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    sources = session.scalars(
        select(ProjectSource).where(
            ProjectSource.project_id == project_id,
            ProjectSource.provider == "trello",
            ProjectSource.enabled.is_(True),
        )
    ).all()

    if not sources:
        return {"completed": [], "errors": []}

    token = refresh_if_needed(session, user_id)
    if not token:
        raise TrelloReconnectRequired

    existing_mappings = session.scalars(
        select(ColumnMapping).where(ColumnMapping.project_id == project_id)
    ).all()
    existing_categories = {m.column_uid: m.category for m in existing_mappings}

    completed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total = len(sources)

    for index, source in enumerate(sources):
        board_id = source.external_id
        if progress_callback:
            progress_callback(
                index,
                total,
                f"Coletando dados do board Trello: {source.display_name or board_id}",
            )

        try:
            payload = fetch_board_data(token, board_id)
            transformed = transform_trello_board_payload(
                payload,
                project_id,
                existing_column_categories=existing_categories,
            )

            nodes_counts: dict[str, int] = {}
            for label, nlist in transformed["nodes"].items():
                if nlist:
                    writer.upsert_nodes(project_id, label, nlist)
                    nodes_counts[label] = len(nlist)

            rel_counts: dict[str, int] = {}
            for (src_label, rel_type, tgt_label), rlist in transformed["relationships"].items():
                if rlist:
                    written = writer.upsert_relationships_if_present(
                        project_id,
                        src_label,
                        rel_type,
                        tgt_label,
                        rlist,
                    )[0]
                    rel_counts[f"{src_label}:{rel_type}:{tgt_label}"] = written

            for link in transformed["relacionada_links"]:
                tgt_label = link.get("target_label") or (
                    "PullRequest" if link.get("target_kind") == "pull" else "Task"
                )
                writer.upsert_relationships_if_present(
                    project_id,
                    "Task",
                    "RELACIONADA_A",
                    tgt_label,
                    [link],
                )

            for col_uid, col_info in transformed["new_column_mappings"].items():
                if col_uid not in existing_categories:
                    new_mapping = ColumnMapping(
                        project_id=project_id,
                        column_uid=col_uid,
                        name=col_info["name"],
                        category=col_info["category"],
                        source=col_info["source"],
                    )
                    session.add(new_mapping)
                    existing_categories[col_uid] = col_info["category"]

            source.cursor_json = {"last_sync_at": utc_now().isoformat()}
            session.commit()

            completed.append(
                {
                    "source_id": board_id,
                    "board": source.display_name or board_id,
                    "counts": {
                        "nodes": nodes_counts,
                        "relationships": rel_counts,
                    },
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "source_id": board_id,
                    "code": type(exc).__name__,
                    "message": str(exc),
                }
            )

    if progress_callback:
        progress_callback(total, total, "Coleta do Trello concluída.")

    return {
        "completed": completed,
        "errors": errors,
    }
