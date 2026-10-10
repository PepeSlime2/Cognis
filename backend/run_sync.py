"""
Orquestra a coleta completa: GitHub + Trello -> Neo4j.

Uso:
    python run_sync.py

Depois, quando o backend FastAPI existir, o corpo da função `run_sync()`
é exatamente o que vai dentro do endpoint POST /sync.
"""
from config import github_config, trello_config
from github_collector import collect_repo
from neo4j_writer import Neo4jWriter
from trello_collector import collect_board


def run_sync() -> dict:
    resultado = {"github_repos": [], "trello_boards": [], "erros": []}

    with Neo4jWriter() as writer:
        writer.ensure_constraints()

        for repo in github_config.repo_list:
            try:
                collect_repo(repo, writer)
                resultado["github_repos"].append(repo)
            except Exception as e:  # nao derruba o sync inteiro por causa de 1 repo
                resultado["erros"].append(f"github:{repo}: {e}")

        for board_id in trello_config.board_list:
            try:
                collect_board(board_id, writer)
                resultado["trello_boards"].append(board_id)
            except Exception as e:
                resultado["erros"].append(f"trello:{board_id}: {e}")

    return resultado


if __name__ == "__main__":
    resultado = run_sync()
    print("\n--- resumo ---")
    print(resultado)
