from app.database import create_neo4j_driver
from app.db.session import SessionLocal
from app.people_router import get_project_people
from app.db.models import User, Project, PersonOverride

pid = "2914f755-6e4b-4b25-8927-44720c69212f"
db = SessionLocal()
proj = db.query(Project).filter(Project.id == pid).first()
driver = create_neo4j_driver()

res = get_project_people(project_id=pid, user_id=proj.user_id, session=db, driver=driver)
print("Total people in response:", len(res["people"]))
for p in res["people"]:
    print("Person:", p["person_uid"], "excluded:", p.get("excluded"), "is_bot:", p.get("is_bot"), "display_name:", p.get("display_name"))

overrides = db.query(PersonOverride).filter(PersonOverride.project_id == pid).all()
print("Overrides in sqlite:", [(o.person_uid, o.display_name, o.excluded) for o in overrides])
