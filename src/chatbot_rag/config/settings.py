"""基于环境变量的应用配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigurationError(ValueError):
    """必需的应用配置无效时抛出的异常。"""


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
    media_path: Path = Path(".data/media")
    remote_image_hosts: tuple[str, ...] = (
        "alidocs.oss-cn-zhangjiakou.aliyuncs.com",
    )
    qdrant_path: Path = Path(".data/qdrant")
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    knowledge_base_name: str = "project_knowledge"
    knowledge_collection: str = "project_knowledge"
    chunk_size: int = 512
    chunk_overlap: int = 64
    rag_top_k: int = 5

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
        media_path = source.get(
            "CHATBOT_MEDIA_PATH",
            ".data/media",
        ).strip()
        remote_image_hosts = _read_remote_image_hosts(
            source.get(
                "CHATBOT_REMOTE_IMAGE_HOSTS",
                "alidocs.oss-cn-zhangjiakou.aliyuncs.com",
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
