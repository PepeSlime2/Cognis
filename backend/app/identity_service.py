from __future__ import annotations

import difflib
import unicodedata
from typing import Any

from neo4j import Driver
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models import PersonOverride, ProviderConnection
from .neo4j_v2_writer import make_uid


def ensure_people_for_accounts(
    driver: Driver,
    project_id: str,
    overrides_by_uid: dict[str, PersonOverride] | None = None,
) -> dict[str, int]:
    """
    Garante a criação automática 1:1 de nós Person para cada Account que ainda
    não esteja conectada por uma aresta TEM_CONTA.
    - Bots (is_bot=true) geram Person com excluded=true por padrão.
    - Contas humanas geram Person com excluded=false por padrão.
    - Se houver PersonOverride no SQLite, seus valores têm precedência.
    """
    find_unlinked_cypher = """
    MATCH (a:Account {project_id: $project_id})
    WHERE NOT (:Person {project_id: $project_id})-[:TEM_CONTA]->(a)
    RETURN a.uid AS account_uid,
           a.login AS login,
           a.display_name AS display_name,
           a.provider AS provider,
           coalesce(a.is_bot, false) AS is_bot
    """

    with driver.session() as session:
        records = session.run(find_unlinked_cypher, project_id=project_id)
        rows: list[dict[str, Any]] = []

        for record in records:
            account_uid = record["account_uid"]
            parts = account_uid.split("|")
            external_id = parts[3] if len(parts) >= 4 else account_uid.replace("|", "_")
            provider = record["provider"] or "unknown"

            person_external_id = f"{provider}_{external_id}"
            person_uid = make_uid(project_id, "person", "cognis", person_external_id)

            display_name = record["display_name"] or record["login"] or "Colaborador"
            excluded = bool(record["is_bot"])

            if overrides_by_uid and person_uid in overrides_by_uid:
                override = overrides_by_uid[person_uid]
                if override.display_name is not None and override.display_name.strip():
                    display_name = override.display_name.strip()
                excluded = bool(override.excluded)

            rows.append(
                {
                    "project_id": project_id,
                    "person_uid": person_uid,
                    "account_uid": account_uid,
                    "display_name": display_name,
                    "excluded": excluded,
                }
            )

        if not rows:
            return {"people_created": 0, "relationships_created": 0}

        upsert_cypher = """
        UNWIND $rows AS row
        MERGE (p:Person {uid: row.person_uid})
        ON CREATE SET p.project_id = row.project_id,
                      p.display_name = row.display_name,
                      p.excluded = row.excluded
        WITH p, row
        MATCH (a:Account {uid: row.account_uid, project_id: row.project_id})
        MERGE (p)-[:TEM_CONTA]->(a)
        RETURN count(p) AS created
        """

        def _execute(tx: Any) -> int:
            res = tx.run(upsert_cypher, rows=rows)
            single = res.single()
            return single["created"] if single else 0

        created_count = session.execute_write(_execute)
        return {
            "people_created": created_count,
            "relationships_created": created_count,
        }


def apply_person_overrides(
    driver: Driver,
    project_id: str,
    overrides: list[PersonOverride],
) -> int:
    """Aplica person_overrides salvos no SQLite sobre os nós Person correspondentes no Neo4j."""
    if not overrides:
        return 0

    rows = [
        {
            "project_id": project_id,
            "person_uid": ov.person_uid,
            "display_name": ov.display_name,
            "excluded": bool(ov.excluded),
        }
        for ov in overrides
    ]

    cypher = """
    UNWIND $rows AS row
    MATCH (p:Person {uid: row.person_uid, project_id: row.project_id})
    SET p.excluded = row.excluded
    FOREACH (_ IN CASE WHEN row.display_name IS NOT NULL AND trim(row.display_name) <> '' THEN [1] ELSE [] END |
        SET p.display_name = trim(row.display_name)
    )
    RETURN count(p) AS updated
    """

    def _execute(tx: Any) -> int:
        res = tx.run(cypher, rows=rows)
        single = res.single()
        return single["updated"] if single else 0

    with driver.session() as session:
        return session.execute_write(_execute)


def sync_people_for_project(
    driver: Driver,
    project_id: str,
    db_session: Session,
) -> dict[str, int]:
    """Orquestra a criação 1:1 e a sincronização de overrides para um projeto."""
    overrides = list(
        db_session.scalars(
            select(PersonOverride).where(PersonOverride.project_id == project_id)
        ).all()
    )
    overrides_by_uid = {ov.person_uid: ov for ov in overrides}

    stats = ensure_people_for_accounts(
        driver, project_id, overrides_by_uid=overrides_by_uid
    )
    apply_person_overrides(driver, project_id, overrides)
    return stats


def list_people_for_project(
    driver: Driver,
    project_id: str,
    user_id: str | None = None,
    db_session: Session | None = None,
) -> list[dict[str, Any]]:
    """
    Lista todos os nós Person do projeto com suas respectivas contas associadas via TEM_CONTA.
    Marca is_me=True para a Person conectada pelo usuário logado (sem gravar no grafo).
    """
    connected_logins: set[str] = set()
    if user_id and db_session:
        connections = db_session.scalars(
            select(ProviderConnection).where(ProviderConnection.user_id == user_id)
        ).all()
        for conn in connections:
            if conn.external_login:
                connected_logins.add(conn.external_login.strip().casefold())

    cypher = """
    MATCH (p:Person {project_id: $project_id})
    OPTIONAL MATCH (p)-[:TEM_CONTA]->(a:Account {project_id: $project_id})
    RETURN p.uid AS person_uid,
           p.display_name AS display_name,
           coalesce(p.excluded, false) AS excluded,
           collect(CASE WHEN a IS NOT NULL THEN {
               uid: a.uid,
               provider: a.provider,
               login: a.login,
               display_name: a.display_name,
               avatar_url: a.avatar_url,
               is_bot: coalesce(a.is_bot, false),
               linked: coalesce(a.linked, true)
           } ELSE null END) AS raw_accounts
    ORDER BY p.display_name ASC
    """

    with driver.session() as session:
        records = session.run(cypher, project_id=project_id)
        people: list[dict[str, Any]] = []

        for record in records:
            raw_accounts = record["raw_accounts"] or []
            accounts = [acc for acc in raw_accounts if acc is not None]

            is_me = False
            for acc in accounts:
                login = acc.get("login")
                if isinstance(login, str) and login.strip().casefold() in connected_logins:
                    is_me = True
                    break

            people.append(
                {
                    "person_uid": record["person_uid"],
                    "display_name": record["display_name"],
                    "excluded": record["excluded"],
                    "is_me": is_me,
                    "accounts": accounts,
                }
            )

        return people


def normalize_name(name: str | None) -> str:
    """Normaliza nome para minúsculas, sem acentos e espaços reduzidos."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name.strip().lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def find_merge_suggestions(people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Gera sugestões automáticas de mesclagem (não aplicadas sozinhas) conforme SPEC §6.1:
    - Pares (Account GitHub, Account Trello) com nome idêntico ou similaridade >= 0.85.
    - Autor de commit linked=false com mesmo display_name de uma Person.
    """
    suggestions: list[dict[str, Any]] = []
    seen_pairs: set[frozenset[str]] = set()

    # 1. Sugestões entre contas GitHub e Trello de pessoas distintas
    for i, person_a in enumerate(people):
        for person_b in people[i + 1 :]:
            pair_key = frozenset([person_a["person_uid"], person_b["person_uid"]])
            if pair_key in seen_pairs:
                continue

            for acc_a in person_a["accounts"]:
                for acc_b in person_b["accounts"]:
                    prov_a = acc_a.get("provider")
                    prov_b = acc_b.get("provider")
                    # Comparar GitHub <-> Trello
                    if {prov_a, prov_b} == {"github", "trello"}:
                        name_a = normalize_name(acc_a.get("display_name") or acc_a.get("login"))
                        name_b = normalize_name(acc_b.get("display_name") or acc_b.get("login"))
                        login_a = normalize_name(acc_a.get("login"))
                        login_b = normalize_name(acc_b.get("login"))

                        if not name_a or not name_b:
                            continue

                        ratio_names = difflib.SequenceMatcher(None, name_a, name_b).ratio()
                        ratio_logins = difflib.SequenceMatcher(None, login_a, login_b).ratio()
                        best_ratio = max(ratio_names, ratio_logins)

                        if name_a == name_b or login_a == login_b:
                            seen_pairs.add(pair_key)
                            suggestions.append(
                                {
                                    "person_a_uid": person_a["person_uid"],
                                    "person_b_uid": person_b["person_uid"],
                                    "account_a": acc_a,
                                    "account_b": acc_b,
                                    "reason": "Nome idêntico entre GitHub e Trello",
                                    "confidence": 1.0,
                                }
                            )
                            break
                        elif best_ratio >= 0.85:
                            seen_pairs.add(pair_key)
                            suggestions.append(
                                {
                                    "person_a_uid": person_a["person_uid"],
                                    "person_b_uid": person_b["person_uid"],
                                    "account_a": acc_a,
                                    "account_b": acc_b,
                                    "reason": f"Alta similaridade de identificador ({int(best_ratio * 100)}%)",
                                    "confidence": round(best_ratio, 2),
                                }
                            )
                            break

    # 2. Autores de commit git com linked=false com mesmo display_name de uma Person
    for person_git in people:
        for acc in person_git["accounts"]:
            if acc.get("provider") == "git" and acc.get("linked") is False:
                norm_git_name = normalize_name(acc.get("display_name"))
                if not norm_git_name:
                    continue

                for person_target in people:
                    if person_target["person_uid"] == person_git["person_uid"]:
                        continue
                    pair_key = frozenset([person_git["person_uid"], person_target["person_uid"]])
                    if pair_key in seen_pairs:
                        continue

                    norm_target_name = normalize_name(person_target["display_name"])
                    if norm_git_name == norm_target_name:
                        seen_pairs.add(pair_key)
                        target_acc = person_target["accounts"][0] if person_target["accounts"] else None
                        suggestions.append(
                            {
                                "person_a_uid": person_target["person_uid"],
                                "person_b_uid": person_git["person_uid"],
                                "account_a": target_acc,
                                "account_b": acc,
                                "reason": "Autor de commit git com mesmo nome de colaborador",
                                "confidence": 0.90,
                            }
                        )
                        break

    suggestions.sort(key=lambda s: s["confidence"], reverse=True)
    return suggestions


def merge_people(
    driver: Driver,
    project_id: str,
    keep_person_uid: str,
    merge_person_uids: list[str],
) -> dict[str, Any]:
    """
    Mescla pessoas no grafo: move as relações TEM_CONTA das pessoas mescladas
    para a mantida (keep_person_uid) e apaga as Person vazias resultantes.
    """
    clean_merge_uids = [uid for uid in merge_person_uids if uid != keep_person_uid]
    if not clean_merge_uids:
        raise ValueError("A lista de pessoas para mesclar não pode conter apenas a mantida.")

    verify_cypher = """
    MATCH (keep:Person {uid: $keep_person_uid, project_id: $project_id})
    RETURN keep.uid AS uid
    """
    merge_cypher = """
    MATCH (keep:Person {uid: $keep_person_uid, project_id: $project_id})
    MATCH (m:Person {project_id: $project_id})
    WHERE m.uid IN $merge_uids AND m.uid <> $keep_person_uid
    OPTIONAL MATCH (m)-[r:TEM_CONTA]->(a:Account {project_id: $project_id})
    FOREACH (_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END |
        MERGE (keep)-[:TEM_CONTA]->(a)
        DELETE r
    )
    WITH m
    WHERE NOT (m)-[:TEM_CONTA]->(:Account)
    DELETE m
    """
    fetch_cypher = """
    MATCH (keep:Person {uid: $keep_person_uid, project_id: $project_id})
    OPTIONAL MATCH (keep)-[:TEM_CONTA]->(a:Account {project_id: $project_id})
    RETURN keep.uid AS person_uid,
           keep.display_name AS display_name,
           coalesce(keep.excluded, false) AS excluded,
           collect(CASE WHEN a IS NOT NULL THEN {
               uid: a.uid,
               provider: a.provider,
               login: a.login,
               display_name: a.display_name,
               avatar_url: a.avatar_url,
               is_bot: coalesce(a.is_bot, false),
               linked: coalesce(a.linked, true)
           } ELSE null END) AS accounts
    """

    with driver.session() as session:
        check = session.run(verify_cypher, keep_person_uid=keep_person_uid, project_id=project_id).single()
        if not check:
            raise ValueError(f"Pessoa mantida não encontrada: {keep_person_uid}")

        def _exec_merge(tx: Any):
            tx.run(merge_cypher, keep_person_uid=keep_person_uid, merge_uids=clean_merge_uids, project_id=project_id)
            res = tx.run(fetch_cypher, keep_person_uid=keep_person_uid, project_id=project_id)
            return res.single()

        result_record = session.execute_write(_exec_merge)
        if not result_record:
            raise RuntimeError("Não foi possível recuperar a pessoa após a mesclagem.")

        raw_accounts = result_record["accounts"] or []
        accounts = [acc for acc in raw_accounts if acc is not None]
        return {
            "person_uid": result_record["person_uid"],
            "display_name": result_record["display_name"],
            "excluded": result_record["excluded"],
            "accounts": accounts,
        }


def split_person(
    driver: Driver,
    project_id: str,
    person_uid: str,
    account_uid: str,
) -> dict[str, Any]:
    """
    Desfaz a mesclagem de uma conta: remove o vínculo TEM_CONTA entre person_uid e account_uid,
    e cria uma nova Person 1:1 para a account_uid destacada.
    """
    check_cypher = """
    MATCH (p:Person {uid: $person_uid, project_id: $project_id})
    MATCH (p)-[:TEM_CONTA]->(target:Account {uid: $account_uid, project_id: $project_id})
    MATCH (p)-[:TEM_CONTA]->(all_acc:Account {project_id: $project_id})
    RETURN count(all_acc) AS total_accounts,
           target.provider AS provider,
           target.login AS login,
           target.display_name AS display_name,
           coalesce(target.is_bot, false) AS is_bot
    """

    with driver.session() as session:
        record = session.run(
            check_cypher,
            person_uid=person_uid,
            account_uid=account_uid,
            project_id=project_id,
        ).single()

        if not record or record["total_accounts"] == 0:
            raise ValueError("Conta não encontrada vinculada à pessoa informada.")
        if record["total_accounts"] <= 1:
            raise ValueError("A pessoa possui apenas uma conta vinculada e não pode ser dividida.")

        provider = record["provider"] or "unknown"
        parts = account_uid.split("|")
        external_id = parts[3] if len(parts) >= 4 else account_uid.replace("|", "_")
        new_person_uid = make_uid(project_id, "person", "cognis", f"{provider}_{external_id}")
        if new_person_uid == person_uid:
            new_person_uid = f"{new_person_uid}_split"

        split_cypher = """
        MATCH (p:Person {uid: $person_uid, project_id: $project_id})-[r:TEM_CONTA]->(a:Account {uid: $account_uid, project_id: $project_id})
        DELETE r
        WITH a
        MERGE (new_p:Person {uid: $new_person_uid})
        ON CREATE SET new_p.project_id = $project_id,
                      new_p.display_name = a.display_name,
                      new_p.excluded = coalesce(a.is_bot, false)
        MERGE (new_p)-[:TEM_CONTA]->(a)
        RETURN new_p.uid AS new_uid, new_p.display_name AS new_name, new_p.excluded AS new_excluded
        """

        def _exec_split(tx: Any):
            res = tx.run(
                split_cypher,
                person_uid=person_uid,
                account_uid=account_uid,
                new_person_uid=new_person_uid,
                project_id=project_id,
            )
            return res.single()

        new_rec = session.execute_write(_exec_split)

        # Buscar dados atualizados de ambas as pessoas
        original_people = list_people_for_project(driver, project_id)
        original_person = next((p for p in original_people if p["person_uid"] == person_uid), None)
        new_person = next((p for p in original_people if p["person_uid"] == new_person_uid), None)

        return {
            "original_person": original_person,
            "new_person": new_person,
        }

