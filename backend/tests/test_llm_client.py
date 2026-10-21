import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.database import get_neo4j_driver
from app.llm.client import (
    OllamaAPIError,
    OllamaConnectionError,
    OllamaTimeoutError,
    chat,
    check_ollama_health,
)
from app.main import app
from starlette.testclient import TestClient


class MockResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text or (str(json_data) if json_data else "")

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


# ==============================================================================
# Health Check Tests
# ==============================================================================

def test_check_ollama_health_model_present():
    with patch("requests.get") as mock_get:
        mock_get.return_value = MockResponse(
            status_code=200,
            json_data={
                "models": [
                    {"name": "llama3.1:8b", "size": 4920736512},
                    {"name": "nomic-embed-text:latest", "size": 274302450},
                ]
            },
        )
        health = check_ollama_health(host="http://localhost:11434", model="llama3.1:8b")
        assert health["status"] == "ok"
        assert health["available"] is True
        assert health["model"] == "llama3.1:8b"
        assert "llama3.1:8b" in health["installed_models"]


def test_check_ollama_health_model_missing():
    with patch("requests.get") as mock_get:
        mock_get.return_value = MockResponse(
            status_code=200,
            json_data={
                "models": [
                    {"name": "mistral:7b"},
                ]
            },
        )
        health = check_ollama_health(host="http://localhost:11434", model="llama3.1:8b")
        assert health["status"] == "unavailable"
        assert health["available"] is False
        assert "não encontrado" in health["reason"]


def test_check_ollama_health_timeout():
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Timed out")):
        health = check_ollama_health()
        assert health["status"] == "unavailable"
        assert health["available"] is False
        assert "Timeout" in health["error"]


def test_check_ollama_health_connection_error():
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("Refused")):
        health = check_ollama_health()
        assert health["status"] == "unavailable"
        assert health["available"] is False
        assert "inacessível" in health["error"]


def test_check_ollama_health_http_error():
    with patch("requests.get") as mock_get:
        mock_get.return_value = MockResponse(status_code=500, text="Internal Error")
        health = check_ollama_health()
        assert health["status"] == "unavailable"
        assert health["available"] is False
        assert "HTTP 500" in health["error"]


# ==============================================================================
# Chat Client Tests
# ==============================================================================

def test_chat_success():
    with patch("requests.post") as mock_post:
        mock_post.return_value = MockResponse(
            status_code=200,
            json_data={
                "message": {"role": "assistant", "content": "Olá, eu sou o Cognis!"}
            },
        )

        messages = [{"role": "user", "content": "Olá"}]
        result = chat(messages)

        assert result == "Olá, eu sou o Cognis!"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["model"] == "llama3.1:8b"
        assert payload["messages"] == messages
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.2
        assert payload["options"]["num_ctx"] == 8192
        assert payload["options"]["seed"] == 42
        assert payload["keep_alive"] == "10m"


def test_chat_with_json_schema():
    class DummySchema:
        @classmethod
        def model_json_schema(cls):
            return {"type": "object", "properties": {"summary": {"type": "string"}}}

    with patch("requests.post") as mock_post:
        mock_post.return_value = MockResponse(
            status_code=200,
            json_data={"message": {"role": "assistant", "content": '{"summary": "ok"}'}},
        )

        result = chat([{"role": "user", "content": "Resuma"}], format=DummySchema)
        assert result == '{"summary": "ok"}'
        payload = mock_post.call_args[1]["json"]
        assert payload["format"] == {"type": "object", "properties": {"summary": {"type": "string"}}}


def test_chat_timeout_raises():
    with patch("requests.post", side_effect=requests.exceptions.Timeout("Timeout")):
        with pytest.raises(OllamaTimeoutError) as exc_info:
            chat([{"role": "user", "content": "Teste"}], timeout_s=5.0)
        assert "Tempo limite esgotado" in str(exc_info.value)


def test_chat_connection_error_raises():
    with patch("requests.post", side_effect=requests.exceptions.ConnectionError("Conn error")):
        with pytest.raises(OllamaConnectionError) as exc_info:
            chat([{"role": "user", "content": "Teste"}])
        assert "Não foi possível conectar" in str(exc_info.value)


def test_chat_api_error_http():
    with patch("requests.post") as mock_post:
        mock_post.return_value = MockResponse(status_code=500, text="Crash")
        with pytest.raises(OllamaAPIError) as exc_info:
            chat([{"role": "user", "content": "Teste"}])
        assert "HTTP 500" in str(exc_info.value)
        assert exc_info.value.status_code == 500


# ==============================================================================
# Strict Concurrency Serialization Test
# ==============================================================================

def test_chat_concurrency_lock_serialization():
    """
    Testa se o _llm_lock serializa estritamente múltiplas chamadas simultâneas.
    Nenhum momento pode ter mais de 1 chamada ativa dentro da seção crítica.
    """
    active_count = 0
    max_concurrent = 0
    tracker_lock = threading.Lock()
    call_order: list[str] = []

    def mock_sleepy_post(*args, **kwargs):
        nonlocal active_count, max_concurrent
        with tracker_lock:
            active_count += 1
            if active_count > max_concurrent:
                max_concurrent = active_count
        
        # Simula trabalho de inferência do LLM
        time.sleep(0.08)

        caller_id = kwargs.get("json", {}).get("messages", [{}])[0].get("content")
        with tracker_lock:
            call_order.append(caller_id)
            active_count -= 1

        return MockResponse(
            status_code=200,
            json_data={"message": {"role": "assistant", "content": f"Echo {caller_id}"}},
        )

    with patch("requests.post", side_effect=mock_sleepy_post):
        results: dict[str, str] = {}

        def worker(tag: str):
            res = chat([{"role": "user", "content": tag}])
            results[tag] = res

        threads = [
            threading.Thread(target=worker, args=(f"thread-{i}",))
            for i in range(3)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # O lock do LLM garante que nunca mais de 1 chamada executou ao mesmo tempo
        assert max_concurrent == 1
        assert len(call_order) == 3
        for i in range(3):
            assert results[f"thread-{i}"] == f"Echo thread-{i}"


# ==============================================================================
# Endpoint /health Integration
# ==============================================================================

def test_api_health_endpoint():
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.return_value = True
    app.dependency_overrides[get_neo4j_driver] = lambda: mock_driver

    try:
        with patch("app.main.check_ollama_health") as mock_health:
            mock_health.return_value = {
                "status": "ok",
                "model": "llama3.1:8b",
                "available": True,
            }

            client = TestClient(app)
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["neo4j"] == "connected"
            assert data["ollama"]["status"] == "ok"
            assert data["ollama"]["model"] == "llama3.1:8b"
    finally:
        app.dependency_overrides.pop(get_neo4j_driver, None)
