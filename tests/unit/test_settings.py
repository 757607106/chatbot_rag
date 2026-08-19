"""应用配置测试。"""

import json
from pathlib import Path

import pytest

from chatbot_rag.config import ConfigurationError, Settings


def test_settings_load_expected_environment_values() -> None:
    """配置应正确映射支持的环境变量。"""
    settings = Settings.from_env(
        {
            "DASHSCOPE_API_KEY": "secret",
            "CHATBOT_MODEL": "qwen-max",
            "CHATBOT_AGENT_NAME": "knowledge_agent",
            "CHATBOT_EMBEDDING_MODEL": "embedding-model",
            "CHATBOT_EMBEDDING_DIMENSIONS": "768",
            "CHATBOT_RERANK_MODEL": "rerank-model",
            "CHATBOT_RERANK_CANDIDATE_TOP_K": "40",
            "CHATBOT_DOCUMENTS_PATH": "knowledge",
            "CHATBOT_KNOWLEDGE_DOCUMENTS_ROOT_PATH": "managed-knowledge",
            "CHATBOT_DOCUMENT_VERSIONS_PATH": "knowledge-versions",
            "CHATBOT_KNOWLEDGE_CATALOG_PATH": "knowledge/catalog.sqlite3",
            "CHATBOT_MEDIA_PATH": "media",
            "CHATBOT_REMOTE_IMAGE_HOSTS": (
                "images.example.com, cdn.example.com,images.example.com"
            ),
            "CHATBOT_QDRANT_PATH": "vectors",
            "CHATBOT_QDRANT_URL": "https://qdrant.example.com",
            "CHATBOT_QDRANT_API_KEY": "qdrant-secret",
            "CHATBOT_KNOWLEDGE_BASE_NAME": "company_docs",
            "CHATBOT_KNOWLEDGE_COLLECTION": "company_docs_v1",
            "CHATBOT_CHUNK_SIZE": "384",
            "CHATBOT_CHUNK_OVERLAP": "48",
            "CHATBOT_RAG_TOP_K": "8",
            "CHATBOT_MAX_UPLOAD_MB": "25",
        },
    )

    assert settings.dashscope_api_key == "secret"
    assert settings.model_name == "qwen-max"
    assert settings.agent_name == "knowledge_agent"
    assert settings.embedding_model_name == "embedding-model"
    assert settings.embedding_dimensions == 768
    assert settings.rerank_model_name == "rerank-model"
    assert settings.rerank_candidate_top_k == 40
    assert settings.documents_path == Path("knowledge")
    assert settings.knowledge_documents_root_path == Path(
        "managed-knowledge",
    )
    assert settings.document_versions_path == Path("knowledge-versions")
    assert settings.knowledge_catalog_path == Path("knowledge/catalog.sqlite3")
    assert settings.media_path == Path("media")
    assert settings.remote_image_hosts == (
        "images.example.com",
        "cdn.example.com",
    )
    assert settings.qdrant_path == Path("vectors")
    assert settings.qdrant_url == "https://qdrant.example.com"
    assert settings.qdrant_api_key == "qdrant-secret"
    assert settings.knowledge_base_name == "company_docs"
    assert settings.knowledge_collection == "company_docs_v1"
    assert settings.chunk_size == 384
    assert settings.chunk_overlap == 48
    assert settings.rag_top_k == 8
    assert settings.max_upload_bytes == 25 * 1024 * 1024


def test_settings_use_defaults_for_optional_empty_values() -> None:
    """空的可选值应使用文档规定的默认值。"""
    settings = Settings.from_env(
        {
            "DASHSCOPE_API_KEY": "secret",
            "CHATBOT_MODEL": " ",
            "CHATBOT_AGENT_NAME": " ",
        },
    )

    assert settings.model_name == "qwen-plus"
    assert settings.agent_name == "assistant"
    assert settings.embedding_model_name == "text-embedding-v4"
    assert settings.embedding_dimensions == 1024
    assert settings.rerank_model_name == "qwen3-rerank"
    assert settings.rerank_candidate_top_k == 50
    assert settings.documents_path == Path("tests/docs_test")
    assert settings.knowledge_documents_root_path == Path(
        ".data/knowledge/documents",
    )
    assert settings.document_versions_path == Path(".data/knowledge/versions")
    assert settings.knowledge_catalog_path == Path(
        ".data/knowledge/catalog.sqlite3",
    )
    assert settings.media_path == Path(".data/media")
    assert settings.remote_image_hosts == (
        "alidocs.oss-cn-zhangjiakou.aliyuncs.com",
        "yunhelp.gmgrasp.com.cn",
    )
    assert settings.qdrant_path == Path(".data/qdrant")
    assert settings.rag_top_k == 5
    assert settings.max_upload_bytes == 50 * 1024 * 1024
    assert (
        settings.realtime_voice_model_name
        == "qwen-audio-3.0-realtime-flash"
    )
    assert settings.realtime_voice_name == "longanqian"
    assert settings.realtime_voice_base_url == (
        "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    )
    assert settings.realtime_voice_allowed_origins == (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )


def test_settings_reject_missing_api_key() -> None:
    """缺少模型凭据时应在配置阶段失败。"""
    with pytest.raises(ConfigurationError, match="DASHSCOPE_API_KEY"):
        Settings.from_env({})


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("CHATBOT_EMBEDDING_DIMENSIONS", "invalid", "must be an integer"),
        ("CHATBOT_CHUNK_SIZE", "0", "greater than zero"),
        ("CHATBOT_CHUNK_OVERLAP", "-1", "must not be negative"),
        ("CHATBOT_RAG_TOP_K", "51", "must not exceed 50"),
        (
            "CHATBOT_RERANK_CANDIDATE_TOP_K",
            "501",
            "must not exceed 500",
        ),
    ],
)
def test_settings_reject_invalid_numeric_rag_values(
    name: str,
    value: str,
    message: str,
) -> None:
    """RAG 数值配置无效时应在启动前失败。"""
    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env({"DASHSCOPE_API_KEY": "secret", name: value})


def test_settings_reject_overlap_not_less_than_chunk_size() -> None:
    """切块重叠长度必须小于切块长度。"""
    with pytest.raises(ConfigurationError, match="must be less than"):
        Settings.from_env(
            {
                "DASHSCOPE_API_KEY": "secret",
                "CHATBOT_CHUNK_SIZE": "64",
                "CHATBOT_CHUNK_OVERLAP": "64",
            },
        )


def test_settings_reject_candidate_count_less_than_final_top_k() -> None:
    """重排序候选数量不得小于最终返回数量。"""
    with pytest.raises(ConfigurationError, match="greater than or equal"):
        Settings.from_env(
            {
                "DASHSCOPE_API_KEY": "secret",
                "CHATBOT_RAG_TOP_K": "10",
                "CHATBOT_RERANK_CANDIDATE_TOP_K": "5",
            },
        )


def test_settings_reject_qdrant_key_without_remote_url() -> None:
    """远程 Qdrant 密钥必须和服务地址同时提供。"""
    with pytest.raises(ConfigurationError, match="requires"):
        Settings.from_env(
            {
                "DASHSCOPE_API_KEY": "secret",
                "CHATBOT_QDRANT_API_KEY": "qdrant-secret",
            },
        )


def test_settings_reject_remote_image_url_in_host_allowlist() -> None:
    """远程图片允许列表只能包含主机名，不能接受完整 URL。"""
    with pytest.raises(ConfigurationError, match="host names only"):
        Settings.from_env(
            {
                "DASHSCOPE_API_KEY": "secret",
                "CHATBOT_REMOTE_IMAGE_HOSTS": "https://images.example.com",
            },
        )


def test_settings_reject_unsafe_resource_id() -> None:
    """进入 URL 与目录的资源标识不能包含路径分隔符。"""
    with pytest.raises(ConfigurationError, match="must contain only"):
        Settings.from_env(
            {
                "DASHSCOPE_API_KEY": "secret",
                "CHATBOT_KNOWLEDGE_BASE_NAME": "unsafe/value",
            },
        )


def test_settings_load_custom_realtime_voice_configuration() -> None:
    """实时语音模型、音色、端点与浏览器来源应支持显式覆盖。"""
    settings = Settings.from_env(
        {
            "DASHSCOPE_API_KEY": "secret",
            "CHATBOT_REALTIME_VOICE_MODEL": "qwen-audio-3.0-realtime-plus",
            "CHATBOT_REALTIME_VOICE_NAME": "longanlingxin",
            "CHATBOT_REALTIME_VOICE_BASE_URL": (
                "wss://workspace.cn-beijing.maas.aliyuncs.com"
                "/api-ws/v1/realtime"
            ),
            "CHATBOT_REALTIME_VOICE_ALLOWED_ORIGINS": (
                "https://chat.example.com,https://chat.example.com"
            ),
        },
    )

    assert settings.realtime_voice_model_name == (
        "qwen-audio-3.0-realtime-plus"
    )
    assert settings.realtime_voice_name == "longanlingxin"
    assert settings.realtime_voice_base_url.startswith("wss://workspace.")
    assert settings.realtime_voice_allowed_origins == (
        "https://chat.example.com",
    )


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        (
            "CHATBOT_REALTIME_VOICE_BASE_URL",
            "https://dashscope.aliyuncs.com/api-ws/v1/realtime",
            "must be a wss URL",
        ),
        (
            "CHATBOT_REALTIME_VOICE_ALLOWED_ORIGINS",
            "*",
            "must contain only HTTP origins",
        ),
    ],
)
def test_settings_reject_invalid_realtime_voice_network_boundaries(
    name: str,
    value: str,
    message: str,
) -> None:
    """实时语音端点与浏览器来源必须使用受控协议。"""
    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(
            {"DASHSCOPE_API_KEY": "secret", name: value},
        )


def test_settings_parse_mcp_servers_with_direct_headers() -> None:
    """mcpServers JSON 应保留直接声明的最终请求 Header。"""
    settings = Settings.from_env(
        {
            "DASHSCOPE_API_KEY": "secret",
            "CHATBOT_MCP_SERVERS_JSON": json.dumps(
                {
                    "mcpServers": {
                        "yunprint-billing": {
                            "type": "sse",
                            "url": "https://test-mcp-server.yuncyb.com/sse",
                            "headers": {
                                "Authorization": "Bearer current-token",
                            },
                            "timeout": 15,
                            "enableTools": [
                                "listProducts",
                                "searchProducts",
                                "listProducts",
                            ],
                        },
                    },
                },
            ),
        },
    )

    assert len(settings.mcp_servers) == 1
    server = settings.mcp_servers[0]
    assert server.name == "yunprint-billing"
    assert server.url == "https://test-mcp-server.yuncyb.com/sse"
    assert server.headers == {"Authorization": "Bearer current-token"}
    assert server.timeout == 15.0
    assert server.enable_tools == ("listProducts", "searchProducts")


@pytest.mark.parametrize(
    ("raw_json", "message"),
    [
        ("not-json", "must be valid JSON"),
        ('{"servers":{}}', "must be an object like"),
        (
            '{"mcpServers":{"stdio-server":{"type":"stdio","command":"x"}}}',
            "unsupported type",
        ),
        (
            '{"mcpServers":{"broken":{"type":"sse","url":""}}}',
            "non-empty 'url'",
        ),
        (
            '{"mcpServers":{"broken":{"type":"sse",'
            '"url":"https://x/mcp"}}}',
            "must use a URL ending",
        ),
        (
            '{"mcpServers":{"bad/name":{"type":"sse","url":"https://x/sse"}}}',
            "not allowed by LLM providers",
        ),
        (
            '{"mcpServers":{"billing":{"type":"sse",'
            '"url":"https://x/sse","headers":{"Authorization":'
            '"Bearer ${MISSING_TOKEN}"}}}}',
            "environment placeholders are not supported",
        ),
        (
            '{"mcpServers":{"billing":{"type":"sse",'
            '"url":"https://x/sse","headers":{"Authorization":123}}}}',
            "header values must be strings",
        ),
        (
            '{"mcpServers":{"billing":{"type":"sse",'
            '"url":"https://x/sse","enableTools":["listProducts",1]}}}',
            "enableTools must be an array",
        ),
    ],
)
def test_settings_reject_invalid_mcp_servers_json(
    raw_json: str,
    message: str,
) -> None:
    """非法 MCP 配置应在启动前失败并给出可定位原因。"""
    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(
            {
                "DASHSCOPE_API_KEY": "secret",
                "CHATBOT_MCP_SERVERS_JSON": raw_json,
            },
        )


def test_settings_reads_optional_management_api_key() -> None:
    """管理密钥应支持配置、空白回落和默认关闭。"""
    configured = Settings.from_env(
        {
            "DASHSCOPE_API_KEY": "secret",
            "CHATBOT_MANAGEMENT_API_KEY": "  admin-secret  ",
        },
    )
    assert configured.management_api_key == "admin-secret"

    blank = Settings.from_env(
        {
            "DASHSCOPE_API_KEY": "secret",
            "CHATBOT_MANAGEMENT_API_KEY": "   ",
        },
    )
    assert blank.management_api_key is None

    default = Settings.from_env({"DASHSCOPE_API_KEY": "secret"})
    assert default.management_api_key is None
