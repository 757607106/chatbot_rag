"""基于环境变量的应用配置。"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigurationError(ValueError):
    """必需的应用配置无效时抛出的异常。"""


# 与 AgentScope MCPClient 名称约束一致：模型侧工具名 mcp__{name}__{tool}
# 仅允许 [a-zA-Z0-9_-]。
_MCP_NAME_PATTERN = re.compile(r"[a-zA-Z0-9_-]+")


@dataclass(frozen=True, slots=True)
class McpServerDefinition:
    """解析后的远程 MCP 服务器定义。"""

    name: str
    url: str
    headers: dict[str, str]
    timeout: float = 30.0
    enable_tools: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class Settings:
    """经过校验的聊天机器人运行时配置。"""

    dashscope_api_key: str
    model_name: str = "qwen-plus"
    agent_name: str = "rag_assistant"
    embedding_model_name: str = "text-embedding-v4"
    embedding_dimensions: int = 1024
    rerank_model_name: str = "qwen3-rerank"
    rerank_candidate_top_k: int = 50
    documents_path: Path = Path("tests/docs_test")
    knowledge_documents_root_path: Path = Path(".data/knowledge/documents")
    document_versions_path: Path = Path(".data/knowledge/versions")
    knowledge_catalog_path: Path = Path(".data/knowledge/catalog.sqlite3")
    media_path: Path = Path(".data/media")
    remote_image_hosts: tuple[str, ...] = (
        "alidocs.oss-cn-zhangjiakou.aliyuncs.com",
        "yunhelp.gmgrasp.com.cn",
    )
    qdrant_path: Path = Path(".data/qdrant")
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    knowledge_base_name: str = "project_knowledge"
    knowledge_collection: str = "project_knowledge"
    chunk_size: int = 512
    chunk_overlap: int = 64
    rag_top_k: int = 5
    max_upload_bytes: int = 50 * 1024 * 1024
    asr_model_name: str = "qwen3-asr-flash"
    asr_language: str = "zh"
    tts_model_name: str = "qwen-audio-3.0-tts-plus"
    tts_voice: str = "longanlingxin"
    mcp_servers: tuple[McpServerDefinition, ...] = ()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """从环境变量映射创建配置。

        Args:
            environ: 可选的环境变量映射，默认使用 ``os.environ``。

        Returns:
            经过校验的应用配置。

        Raises:
            ConfigurationError: 未提供 ``DASHSCOPE_API_KEY`` 时抛出。
        """
        source = os.environ if environ is None else environ
        api_key = source.get("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            raise ConfigurationError("DASHSCOPE_API_KEY is required")

        model_name = source.get("CHATBOT_MODEL", "qwen-plus").strip()
        agent_name = source.get("CHATBOT_AGENT_NAME", "rag_assistant").strip()
        embedding_model_name = source.get(
            "CHATBOT_EMBEDDING_MODEL",
            "text-embedding-v4",
        ).strip()
        rerank_model_name = source.get(
            "CHATBOT_RERANK_MODEL",
            "qwen3-rerank",
        ).strip()
        documents_path = source.get(
            "CHATBOT_DOCUMENTS_PATH",
            "tests/docs_test",
        ).strip()
        knowledge_documents_root_path = source.get(
            "CHATBOT_KNOWLEDGE_DOCUMENTS_ROOT_PATH",
            ".data/knowledge/documents",
        ).strip()
        document_versions_path = source.get(
            "CHATBOT_DOCUMENT_VERSIONS_PATH",
            ".data/knowledge/versions",
        ).strip()
        knowledge_catalog_path = source.get(
            "CHATBOT_KNOWLEDGE_CATALOG_PATH",
            ".data/knowledge/catalog.sqlite3",
        ).strip()
        media_path = source.get(
            "CHATBOT_MEDIA_PATH",
            ".data/media",
        ).strip()
        remote_image_hosts = _read_remote_image_hosts(
            source.get(
                "CHATBOT_REMOTE_IMAGE_HOSTS",
                "alidocs.oss-cn-zhangjiakou.aliyuncs.com,"
                "yunhelp.gmgrasp.com.cn",
            ),
        )
        qdrant_path = source.get(
            "CHATBOT_QDRANT_PATH",
            ".data/qdrant",
        ).strip()
        qdrant_url = source.get("CHATBOT_QDRANT_URL", "").strip() or None
        qdrant_api_key = (
            source.get("CHATBOT_QDRANT_API_KEY", "").strip() or None
        )
        knowledge_base_name = source.get(
            "CHATBOT_KNOWLEDGE_BASE_NAME",
            "project_knowledge",
        ).strip()
        knowledge_collection = source.get(
            "CHATBOT_KNOWLEDGE_COLLECTION",
            "project_knowledge",
        ).strip()
        embedding_dimensions = _read_positive_int(
            source,
            "CHATBOT_EMBEDDING_DIMENSIONS",
            1024,
        )
        chunk_size = _read_positive_int(
            source,
            "CHATBOT_CHUNK_SIZE",
            512,
        )
        chunk_overlap = _read_non_negative_int(
            source,
            "CHATBOT_CHUNK_OVERLAP",
            64,
        )
        rag_top_k = _read_positive_int(
            source,
            "CHATBOT_RAG_TOP_K",
            5,
        )
        rerank_candidate_top_k = _read_positive_int(
            source,
            "CHATBOT_RERANK_CANDIDATE_TOP_K",
            50,
        )
        max_upload_megabytes = _read_positive_int(
            source,
            "CHATBOT_MAX_UPLOAD_MB",
            50,
        )
        asr_model_name = source.get(
            "CHATBOT_ASR_MODEL",
            "qwen3-asr-flash",
        ).strip()
        asr_language = source.get(
            "CHATBOT_ASR_LANGUAGE",
            "zh",
        ).strip()
        tts_model_name = source.get(
            "CHATBOT_TTS_MODEL",
            "qwen-audio-3.0-tts-plus",
        ).strip()
        tts_voice = source.get(
            "CHATBOT_TTS_VOICE",
            "longanlingxin",
        ).strip()
        mcp_servers = _read_mcp_servers(
            source.get("CHATBOT_MCP_SERVERS_JSON", ""),
        )
        if chunk_overlap >= chunk_size:
            raise ConfigurationError(
                "CHATBOT_CHUNK_OVERLAP must be less than CHATBOT_CHUNK_SIZE",
            )
        if rag_top_k > 50:
            raise ConfigurationError("CHATBOT_RAG_TOP_K must not exceed 50")
        if rerank_candidate_top_k > 500:
            raise ConfigurationError(
                "CHATBOT_RERANK_CANDIDATE_TOP_K must not exceed 500",
            )
        if rerank_candidate_top_k < rag_top_k:
            raise ConfigurationError(
                "CHATBOT_RERANK_CANDIDATE_TOP_K must be greater than or "
                "equal to CHATBOT_RAG_TOP_K",
            )
        if qdrant_api_key is not None and qdrant_url is None:
            raise ConfigurationError(
                "CHATBOT_QDRANT_API_KEY requires CHATBOT_QDRANT_URL",
            )
        if not _is_safe_resource_id(knowledge_base_name):
            raise ConfigurationError(
                "CHATBOT_KNOWLEDGE_BASE_NAME must contain only letters, "
                "numbers, dots, underscores, or hyphens",
            )
        return cls(
            dashscope_api_key=api_key,
            model_name=model_name or "qwen-plus",
            agent_name=agent_name or "rag_assistant",
            embedding_model_name=(
                embedding_model_name or "text-embedding-v4"
            ),
            embedding_dimensions=embedding_dimensions,
            rerank_model_name=rerank_model_name or "qwen3-rerank",
            rerank_candidate_top_k=rerank_candidate_top_k,
            documents_path=Path(documents_path or "tests/docs_test"),
            knowledge_documents_root_path=Path(
                knowledge_documents_root_path
                or ".data/knowledge/documents",
            ),
            document_versions_path=Path(
                document_versions_path or ".data/knowledge/versions",
            ),
            knowledge_catalog_path=Path(
                knowledge_catalog_path
                or ".data/knowledge/catalog.sqlite3",
            ),
            media_path=Path(media_path or ".data/media"),
            remote_image_hosts=remote_image_hosts,
            qdrant_path=Path(qdrant_path or ".data/qdrant"),
            qdrant_url=qdrant_url,
            qdrant_api_key=qdrant_api_key,
            knowledge_base_name=(knowledge_base_name or "project_knowledge"),
            knowledge_collection=(
                knowledge_collection or "project_knowledge"
            ),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            rag_top_k=rag_top_k,
            max_upload_bytes=max_upload_megabytes * 1024 * 1024,
            asr_model_name=asr_model_name or "qwen3-asr-flash",
            asr_language=asr_language or "zh",
            tts_model_name=tts_model_name or "qwen-audio-3.0-tts-plus",
            tts_voice=tts_voice or "longanlingxin",
            mcp_servers=mcp_servers,
        )


def _read_mcp_servers(
    raw_json: str,
) -> tuple[McpServerDefinition, ...]:
    """解析 ``mcpServers`` 风格的 JSON。

    Args:
        raw_json: ``CHATBOT_MCP_SERVERS_JSON`` 原始值，空值表示未启用 MCP。

    Returns:
        按声明顺序排列的 MCP 服务器定义。

    Raises:
        ConfigurationError: JSON 结构非法或服务器类型不受支持时抛出。
    """
    if not raw_json.strip():
        return ()
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise ConfigurationError(
            "CHATBOT_MCP_SERVERS_JSON must be valid JSON",
        ) from error
    if not isinstance(payload, dict) or not isinstance(
        payload.get("mcpServers"),
        dict,
    ):
        raise ConfigurationError(
            'CHATBOT_MCP_SERVERS_JSON must be an object like '
            '{"mcpServers": {...}}',
        )
    servers: list[McpServerDefinition] = []
    for name, spec in payload["mcpServers"].items():
        servers.append(_read_mcp_server(name, spec))
    return tuple(servers)


def _read_mcp_server(
    name: str,
    spec: object,
) -> McpServerDefinition:
    """校验单个 MCP 服务器条目。"""
    if not isinstance(spec, dict):
        raise ConfigurationError(
            f"MCP server '{name}' must be an object",
        )
    server_type = spec.get("type", "sse")
    if server_type not in ("sse", "http"):
        raise ConfigurationError(
            f"MCP server '{name}' has unsupported type '{server_type}'; "
            "only 'sse' and 'http' servers are supported",
        )
    url = spec.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ConfigurationError(
            f"MCP server '{name}' must provide a non-empty 'url'",
        )
    normalized_url = url.strip()
    uses_sse_transport = normalized_url.endswith(
        ("/sse", "/messages/"),
    )
    if server_type == "sse" and not uses_sse_transport:
        raise ConfigurationError(
            f"MCP server '{name}' with type 'sse' must use a URL ending "
            "in '/sse' or '/messages/'",
        )
    if server_type == "http" and uses_sse_transport:
        raise ConfigurationError(
            f"MCP server '{name}' with type 'http' must not use an SSE URL",
        )
    raw_headers = spec.get("headers", {})
    if not isinstance(raw_headers, dict):
        raise ConfigurationError(
            f"MCP server '{name}' headers must be an object",
        )
    headers = _read_mcp_headers(name, raw_headers)
    enable_tools = _read_mcp_tool_names(name, spec.get("enableTools"))
    raw_timeout = spec.get("timeout", 30.0)
    if (
        isinstance(raw_timeout, bool)
        or not isinstance(raw_timeout, (int, float))
        or raw_timeout <= 0
    ):
        raise ConfigurationError(
            f"MCP server '{name}' timeout must be a positive number",
        )
    timeout = float(raw_timeout)
    if not _MCP_NAME_PATTERN.fullmatch(name):
        raise ConfigurationError(
            f"MCP server name '{name}' contains characters not "
            "allowed by LLM providers (only [a-zA-Z0-9_-] are permitted)",
        )
    return McpServerDefinition(
        name=name,
        url=normalized_url,
        headers=headers,
        timeout=timeout,
        enable_tools=enable_tools,
    )


def _read_mcp_headers(
    server_name: str,
    raw_headers: dict[object, object],
) -> dict[str, str]:
    """校验 MCP Header 已经包含最终要发送的字符串。"""
    headers: dict[str, str] = {}
    for header_name, header_value in raw_headers.items():
        if not isinstance(header_name, str) or not header_name.strip():
            raise ConfigurationError(
                f"MCP server '{server_name}' header names must be "
                "non-empty strings",
            )
        if not isinstance(header_value, str):
            raise ConfigurationError(
                f"MCP server '{server_name}' header values must be strings",
            )
        if "${" in header_value:
            raise ConfigurationError(
                f"MCP server '{server_name}' headers must contain final "
                "values; environment placeholders are not supported",
            )
        headers[header_name.strip()] = header_value
    return headers


def _read_mcp_tool_names(
    server_name: str,
    raw_tool_names: object,
) -> tuple[str, ...] | None:
    """校验可选的 MCP 工具允许列表并保留声明顺序。"""
    if raw_tool_names is None:
        return None
    if not isinstance(raw_tool_names, list) or any(
        not isinstance(tool_name, str) or not tool_name.strip()
        for tool_name in raw_tool_names
    ):
        raise ConfigurationError(
            f"MCP server '{server_name}' enableTools must be an array of "
            "non-empty strings",
        )
    return tuple(
        dict.fromkeys(tool_name.strip() for tool_name in raw_tool_names),
    )


def _read_remote_image_hosts(value: str) -> tuple[str, ...]:
    """解析允许代理的远程图片主机列表。"""
    hosts: list[str] = []
    for raw_host in value.split(","):
        host = raw_host.strip().lower().rstrip(".")
        if not host:
            continue
        if any(character in host for character in "/:@"):
            raise ConfigurationError(
                "CHATBOT_REMOTE_IMAGE_HOSTS must contain host names only",
            )
        if host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def _is_safe_resource_id(value: str) -> bool:
    """校验可安全进入 URL 路径和内部目录的资源标识。"""
    return bool(value) and all(
        character.isascii()
        and (character.isalnum() or character in "._-")
        for character in value
    )


def _read_positive_int(
    source: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    """读取正整数配置，并将格式错误统一转换为配置异常。"""
    value = _read_int(source, name, default)
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def _read_non_negative_int(
    source: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    """读取非负整数配置，并拒绝负数。"""
    value = _read_int(source, name, default)
    if value < 0:
        raise ConfigurationError(f"{name} must not be negative")
    return value


def _read_int(
    source: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    """读取整数配置，空值沿用默认值。"""
    raw_value = source.get(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error
