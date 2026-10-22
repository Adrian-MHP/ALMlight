"""Built-in report templates. Users create a report from a template and adapt it freely.

Widgets reference the item/link keys of the shipped *systems_engineering* template; in projects with another
information model, widgets referring to missing types show an error and can be edited.
"""

from __future__ import annotations

from typing import Any

TEMPLATES: dict[str, dict[str, Any]] = {
    "kpi_overview": {
        "title": "Project KPI overview",
        "description": "Platform and process KPIs: reuse, change lead time, re-test effort, variant ratio.",
        "widgets": [
            {"id": "k1", "type": "kpi", "title": "System requirements approved", "width": 3, "metric": "percent",
             "filter": {"types": ["system_requirement"]}, "percent_of": {"states": ["approved"]}, "target": 80},
            {"id": "k2", "type": "kpi", "title": "Open change requests", "width": 3,
             "filter": {"types": ["change_request"], "states": ["submitted", "in_analysis"]}},
            {"id": "k3", "type": "kpi", "title": "Items with suspect links", "width": 3, "filter": {"suspect": True}},
            {"id": "k4", "type": "kpi", "title": "Released system elements", "width": 3, "metric": "percent",
             "filter": {"types": ["system_element"]}, "percent_of": {"states": ["released"]}},
            {"id": "reuse", "type": "reuse", "title": "Reuse rate per module", "width": 6},
            {"id": "lead", "type": "change_lead_time", "title": "Change lead time (request to release)", "width": 6},
            {"id": "retest", "type": "retest_effort", "title": "Re-test effort per variant", "width": 6},
            {"id": "ratio", "type": "variant_ratio", "title": "Module variants vs. offered variants", "width": 6},
        ],
    },
    "requirements_status": {
        "title": "Requirements status",
        "description": "Lifecycle, priorities, coverage and progress of requirements.",
        "widgets": [
            {"id": "c1", "type": "chart", "title": "Requirements by type and state", "width": 6, "group_by": "type",
             "stack_by": "state", "filter": {"types": ["stakeholder_requirement", "system_requirement",
                                                       "element_requirement"]}},
            {"id": "c2", "type": "chart", "title": "System requirements by priority", "width": 6,
             "group_by": "field:priority", "chart": "donut", "filter": {"types": ["system_requirement"]}},
            {"id": "cov", "type": "coverage", "title": "System requirement coverage", "width": 6,
             "coverage_type": "system_requirement"},
            {"id": "t1", "type": "trend", "title": "Requirements created vs. approved", "width": 6, "interval": "week",
             "periods": 12, "cumulative": True, "series": ["created", "released"],
             "filter": {"types": ["system_requirement", "stakeholder_requirement"]}},
            {"id": "tbl", "type": "table", "title": "Must-have requirements not yet approved", "width": 12,
             "filter": {"types": ["system_requirement"], "states": ["draft", "in_review"],
                        "fields": {"priority": "must"}},
             "columns": ["key", "title", "state", "version", "owner", "updated"]},
        ],
    },
    "change_management": {
        "title": "Change management",
        "description": "Change requests and orders: lead times, backlog and status.",
        "widgets": [
            {"id": "lead", "type": "change_lead_time", "title": "Lead time", "width": 12, "interval": "month"},
            {"id": "c1", "type": "chart", "title": "Changes by type and state", "width": 6, "group_by": "type",
             "stack_by": "state", "filter": {"types": ["problem_report", "change_request", "change_order"]}},
            {"id": "c2", "type": "chart", "title": "Change requests by reason", "width": 6, "group_by": "field:reason",
             "chart": "donut", "filter": {"types": ["change_request"]}},
            {"id": "tbl", "type": "table", "title": "Open changes", "width": 12,
             "filter": {"types": ["change_request", "change_order"],
                        "states": ["submitted", "in_analysis", "planned", "in_work", "in_approval"]},
             "columns": ["key", "title", "type", "state", "owner", "updated"], "sort": "-updated"},
        ],
    },
    "verification": {
        "title": "Verification and re-test",
        "description": "What is verified, what must be re-tested per variant, and element maturity.",
        "widgets": [
            {"id": "retest", "type": "retest_effort", "title": "Re-test effort per variant", "width": 12},
            {"id": "cov", "type": "coverage", "title": "System requirement coverage", "width": 6,
             "coverage_type": "system_requirement"},
            {"id": "mat", "type": "maturity", "title": "Maturity of system elements", "width": 6},
            {"id": "c1", "type": "chart", "title": "Test cases by method", "width": 6, "group_by": "field:method",
             "chart": "donut", "filter": {"types": ["test_case"]}},
            {"id": "m1", "type": "matrix", "title": "System requirements × test cases", "width": 6,
             "rows": "system_requirement", "cols": "test_case"},
        ],
    },
    "platform_reuse": {
        "title": "Platform and reuse",
        "description": "Modularisation KPIs: reuse strategy, multi-use of modules and variant economics.",
        "widgets": [
            {"id": "reuse", "type": "reuse", "title": "Reuse rate per module", "width": 12},
            {"id": "c1", "type": "chart", "title": "Elements by reuse strategy", "width": 6,
             "group_by": "field:reuse_strategy", "chart": "donut", "filter": {"types": ["system_element"]}},
            {"id": "c2", "type": "chart", "title": "Elements by level and discipline", "width": 6,
             "group_by": "field:level", "stack_by": "field:discipline", "filter": {"types": ["system_element"]}},
            {"id": "ratio", "type": "variant_ratio", "title": "Module variants vs. offered variants", "width": 12},
        ],
    },
}
