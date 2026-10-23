from app.database import create_neo4j_driver
from app.db.session import SessionLocal
from app.people_router import get_project_people
from app.db.models import User, Project

pid = "2914f755-6e4b-4b25-8927-44720c69212f"
db = SessionLocal()
proj = db.query(Project).filter(Project.id == pid).first()
print("Project owner user_id:", proj.user_id)
user = db.query(User).filter(User.id == proj.user_id).first()
print("Owner email:", user.email if user else "None")

driver = create_neo4j_driver()
try:
    res = get_project_people(project_id=pid, user_id=proj.user_id, session=db, driver=driver)
    print("Result people count:", len(res["people"]))
    for p in res["people"]:
        print(f"  {p['person_uid']} -> display_name: {p.get('display_name')}, accounts: {len(p.get('accounts', []))}")
    print("Suggestions count:", len(res["suggestions"]))
except Exception as e:
    import traceback
    traceback.print_exc()
