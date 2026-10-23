from app.database import create_neo4j_driver
from app.db.session import SessionLocal
from app.db.models import Project

driver = create_neo4j_driver()
with driver.session() as session:
    res = session.run("MATCH (n) WHERE n.project_id CONTAINS '2914' RETURN n.project_id as pid, labels(n) as l, count(n) as cnt")
    for rec in res:
        print(f"pid={repr(rec['pid'])}, label={rec['l']}, cnt={rec['cnt']}")

    # Check Person nodes specifically
    res2 = session.run("MATCH (p:Person) RETURN p.project_id as pid, p.uid as uid, p.name as name")
    print("\n--- Person nodes ---")
    for rec in res2:
        print(rec.data())

    # Check Account nodes
    res3 = session.run("MATCH (a:Account) WHERE a.project_id CONTAINS '2914' RETURN a.project_id as pid, a.login as login, a.provider as provider")
    print("\n--- Account nodes ---")
    for rec in res3:
        print(rec.data())
