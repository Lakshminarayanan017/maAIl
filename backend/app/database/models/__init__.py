"""ORM models.

Imported for their side effect of registering on ``Base.metadata``; Alembic
autogenerate sees only what is imported here.
"""

from app.database.models.account import AccountStatus, ConnectedAccount, OAuthCredential
from app.database.models.detail import ActionItem, Deadline, Task, ThreadInsight
from app.database.models.features import UserFeature
from app.database.models.intelligence import ThreadIntelligence, UserOverride
from app.database.models.memory import (
    ChatConversation,
    ChatMessage,
    MemoryProposal,
    SemanticFact,
)
from app.database.models.session import OAuthState, Session
from app.database.models.thread import EmailMessage, EmailThread, MessageAttachment
from app.database.models.user import User

__all__ = [
    "AccountStatus",
    "ActionItem",
    "ChatConversation",
    "ChatMessage",
    "ConnectedAccount",
    "Deadline",
    "EmailMessage",
    "EmailThread",
    "MemoryProposal",
    "MessageAttachment",
    "OAuthCredential",
    "OAuthState",
    "SemanticFact",
    "Session",
    "Task",
    "ThreadInsight",
    "ThreadIntelligence",
    "User",
    "UserFeature",
    "UserOverride",
]
