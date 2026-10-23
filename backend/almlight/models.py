"""Imports every ORM model so that SQLAlchemy metadata (and Alembic) sees the full schema."""

from almlight.core.db import Base
from almlight.modules.audit.models import AuditEntry
from almlight.modules.baselines.models import Baseline, BaselineItem, BaselineLink
from almlight.modules.boards.models import Board
from almlight.modules.branches.models import Branch, BranchItem
from almlight.modules.collab.models import CollabDraft
from almlight.modules.doc_collections.models import Collection, CollectionEntry
from almlight.modules.doctemplates.models import DocTemplate
from almlight.modules.files.models import FileCheckout
from almlight.modules.identity.models import ApiToken, User
from almlight.modules.images.models import InlineImage
from almlight.modules.integrations.models import (
    ExternalRef,
    IntegrationSetting,
    OutboxEvent,
    Webhook,
    WebhookDelivery,
)
from almlight.modules.items.models import Blob, Comment, Item, ItemVersion
from almlight.modules.links.models import Link
from almlight.modules.notifications.models import Notification, Subscription
from almlight.modules.projects.models import Project, ProjectCounter, ProjectMember
from almlight.modules.queries.models import SavedQuery
from almlight.modules.reports.models import Report
from almlight.modules.verification.models import TestRecord
from almlight.modules.workflow.models import ApprovalRequest, ApprovalVote, WorkflowEvent
from almlight.modules.worklog.models import WorkRecord

__all__ = [
    "ApiToken",
    "ApprovalRequest",
    "ApprovalVote",
    "AuditEntry",
    "Base",
    "Baseline",
    "BaselineItem",
    "BaselineLink",
    "Blob",
    "Board",
    "Branch",
    "BranchItem",
    "CollabDraft",
    "Collection",
    "CollectionEntry",
    "Comment",
    "DocTemplate",
    "ExternalRef",
    "FileCheckout",
    "InlineImage",
    "IntegrationSetting",
    "Item",
    "ItemVersion",
    "Link",
    "Notification",
    "OutboxEvent",
    "Project",
    "ProjectCounter",
    "ProjectMember",
    "Report",
    "SavedQuery",
    "Subscription",
    "TestRecord",
    "User",
    "Webhook",
    "WebhookDelivery",
    "WorkflowEvent",
    "WorkRecord",
]
