"""AgentScope RAG 文档摄取与知识库装配。"""

from chatbot_rag.rag.document_ingestor import (
    DocumentIngestor,
    IngestionStage,
    IngestionSummary,
)
from chatbot_rag.rag.knowledge_base import open_knowledge_base

__all__ = [
    "DocumentIngestor",
    "IngestionStage",
    "IngestionSummary",
    "open_knowledge_base",
]
