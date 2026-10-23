import sys
from app.database import create_neo4j_driver
from app.graph_service import get_project_graph

pid = "2914f755-6e4b-4b25-8927-44720c69212f"
driver = create_neo4j_driver()

for layer in ["all", "people", "tasks", "artifacts"]:
    g = get_project_graph(driver, pid, layer=layer, max_nodes=400, min_weight=1.0, include_bots=False)
    print(f"Layer '{layer}': {len(g['elements']['nodes'])} nodes, {len(g['elements']['edges'])} edges")
    for n in g['elements']['nodes']:
        lbl = n['data']['label'].encode('ascii', 'replace').decode('ascii')
        print(f"   node: {n['data']['id']} ({n['data']['type']}) -> {lbl}")
