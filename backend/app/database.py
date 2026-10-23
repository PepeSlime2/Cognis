from fastapi import Request
from neo4j import Driver, GraphDatabase

from .config import neo4j_config


def create_neo4j_driver() -> Driver:
    return GraphDatabase.driver(
        neo4j_config.uri, auth=(neo4j_config.user, neo4j_config.password)
    )


def get_neo4j_driver(request: Request) -> Driver | None:
    return getattr(request.app.state, "neo4j_driver", None)
