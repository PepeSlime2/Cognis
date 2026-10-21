from __future__ import annotations

import logging
import threading
from typing import Any

import requests

from ..config import ollama_config

logger = logging.getLogger(__name__)

# Lock global: SPEC §9.2 exige estritamente uma chamada ao LLM por vez
_llm_lock = threading.Lock()


class LLMError(Exception):
    """Exceção base para erros na camada de LLM."""


class OllamaConnectionError(LLMError):
    """Falha de conexão com o serviço Ollama."""


class OllamaTimeoutError(LLMError):
    """Timeout ao aguardar resposta do Ollama."""


class OllamaAPIError(LLMError):
    """Erro retornado pela API HTTP do Ollama."""

    def __init__(self, message: str, status_code: int | None = None, response_text: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


def check_ollama_health(
    host: str | None = None,
    model: str | None = None,
    timeout_s: float = 3.0,
) -> dict[str, Any]:
    """
    Verifica a disponibilidade do Ollama e se o modelo configurado está baixado (SPEC §9.1).
    Endpoint: GET {OLLAMA_HOST}/api/tags
    """
    target_host = (host or ollama_config.host).rstrip("/")
    target_model = model or ollama_config.model

    try:
        resp = requests.get(f"{target_host}/api/tags", timeout=timeout_s)
    except requests.exceptions.Timeout as exc:
        logger.warning("Timeout ao verificar health do Ollama em %s: %s", target_host, exc)
        return {
            "status": "unavailable",
            "model": target_model,
            "available": False,
            "error": "Timeout ao conectar ao Ollama",
        }
    except requests.exceptions.RequestException as exc:
        logger.warning("Falha de conexão ao verificar health do Ollama em %s: %s", target_host, exc)
        return {
            "status": "unavailable",
            "model": target_model,
            "available": False,
            "error": "Serviço Ollama inacessível",
        }

    if resp.status_code != 200:
        logger.warning("Ollama /api/tags retornou HTTP %s: %s", resp.status_code, resp.text)
        return {
            "status": "unavailable",
            "model": target_model,
            "available": False,
            "error": f"HTTP {resp.status_code}",
        }

    try:
        data = resp.json()
    except Exception as exc:
        return {
            "status": "unavailable",
            "model": target_model,
            "available": False,
            "error": f"JSON inválido do Ollama: {exc}",
        }

    installed_models: list[str] = []
    for item in data.get("models", []):
        name = item.get("name") or item.get("model")
        if name:
            installed_models.append(str(name))

    # Verificar se o modelo alvo está presente (exato ou sem tag de versão)
    target_clean = target_model.split(":")[0]
    is_model_present = any(
        m == target_model or m.startswith(f"{target_model}:") or m.startswith(f"{target_clean}:")
        for m in installed_models
    )

    if is_model_present:
        return {
            "status": "ok",
            "model": target_model,
            "available": True,
            "installed_models": installed_models,
        }

    return {
        "status": "unavailable",
        "model": target_model,
        "available": False,
        "reason": f"Modelo '{target_model}' não encontrado. Execute 'ollama pull {target_model}'.",
        "installed_models": installed_models,
    }


def chat(
    messages: list[dict[str, str]],
    format: dict[str, Any] | str | None = None,
    options: dict[str, Any] | None = None,
    host: str | None = None,
    model: str | None = None,
    timeout_s: float | None = None,
) -> str:
    """
    Executa chamada síncrona ao endpoint POST /api/chat do Ollama (SPEC §9.2).
    Garante serialização estrita através do lock global _llm_lock.
    Retorna o texto de content contido em response['message']['content'].
    """
    target_host = (host or ollama_config.host).rstrip("/")
    target_model = model or ollama_config.model
    timeout = timeout_s if timeout_s is not None else ollama_config.timeout_s

    # Resolver format se for classe com model_json_schema (Pydantic v2)
    resolved_format = format
    if hasattr(format, "model_json_schema"):
        resolved_format = getattr(format, "model_json_schema")()

    # Montar opções padrão conforme SPEC §9.1 e §9.2
    default_options: dict[str, Any] = {
        "temperature": ollama_config.temperature,
        "num_ctx": ollama_config.num_ctx,
        "seed": ollama_config.seed,
    }
    if options:
        default_options.update(options)

    payload: dict[str, Any] = {
        "model": target_model,
        "messages": messages,
        "stream": False,
        "options": default_options,
        "keep_alive": ollama_config.keep_alive,
    }
    if resolved_format is not None:
        payload["format"] = resolved_format

    # Serialização estrita: uma chamada ao LLM por vez
    with _llm_lock:
        logger.debug("Executando chamada LLM para %s/api/chat (modelo=%s)", target_host, target_model)
        try:
            resp = requests.post(
                f"{target_host}/api/chat",
                json=payload,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as exc:
            logger.error("Timeout na chamada ao Ollama (%s s): %s", timeout, exc)
            raise OllamaTimeoutError(
                f"Tempo limite esgotado ({timeout}s) aguardando resposta do modelo local Ollama."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            logger.error("Erro de conexão com o Ollama em %s: %s", target_host, exc)
            raise OllamaConnectionError(
                f"Não foi possível conectar ao serviço Ollama em {target_host}."
            ) from exc
        except requests.exceptions.RequestException as exc:
            logger.error("Erro genérico de requisição ao Ollama: %s", exc)
            raise OllamaAPIError(f"Erro na requisição ao Ollama: {exc}") from exc

        if resp.status_code != 200:
            logger.error("Ollama retornou HTTP %s: %s", resp.status_code, resp.text)
            raise OllamaAPIError(
                f"Ollama retornou erro HTTP {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                response_text=resp.text,
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise OllamaAPIError(f"Resposta inválida (não JSON) do Ollama: {resp.text}") from exc

        message = data.get("message", {})
        content = message.get("content", "")
        return content
