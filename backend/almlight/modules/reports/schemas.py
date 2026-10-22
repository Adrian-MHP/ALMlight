"""Widget definitions of user-built reports (stored as JSON, validated here)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WidgetType = Literal[
    "kpi", "chart", "table", "trend", "coverage", "matrix", "markdown",
    "reuse", "change_lead_time", "retest_effort", "variant_ratio", "maturity",
]

COLUMN_CHOICES = ("key", "title", "type", "state", "version", "owner", "updated", "applicability")


class ItemFilter(BaseModel):
    """Selects items, like the item list filters (empty = all items)."""

    model_config = ConfigDict(extra="forbid")

    types: list[str] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)
    q: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    owner: uuid.UUID | None = None
    suspect: bool | None = None
    variant: str | None = Field(default=None, description="Variant key: only items applicable to this variant")


class Widget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40)
    type: WidgetType
    title: str = ""
    width: int = Field(default=6, ge=3, le=12)
    filter: ItemFilter = Field(default_factory=ItemFilter)
    # kpi
    metric: Literal["count", "percent"] = "count"
    percent_of: ItemFilter | None = Field(default=None, description="Numerator filter applied on top of `filter`")
    target: float | None = Field(default=None, description="Goal value (number or percent) for traffic lights")
    # chart
    group_by: str = "state"
    stack_by: str | None = None
    chart: Literal["bar", "horizontal", "donut", "pie"] = "bar"
    # table
    columns: list[str] = Field(default_factory=lambda: ["key", "title", "state", "version", "owner"])
    limit: int = Field(default=50, ge=1, le=500)
    sort: str = "key"
    # trend
    interval: Literal["week", "month"] = "week"
    periods: int = Field(default=12, ge=2, le=104)
    series: list[Literal["created", "released", "changed"]] = Field(default_factory=lambda: ["created", "released"])
    cumulative: bool = False
    # coverage / matrix
    coverage_type: str | None = None
    rows: str | None = None
    cols: str | None = None
    # markdown
    text: str = ""
    # KPI widgets
    change_types: list[str] = Field(default_factory=list)
    variant: str | None = None


class ReportIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    visibility: Literal["project", "private"] = "project"
    widgets: list[Widget] = Field(default_factory=list, max_length=40)
    template: str | None = None
