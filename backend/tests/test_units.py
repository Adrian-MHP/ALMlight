"""Pure unit tests (no database)."""

import pytest

from almlight.core.errors import ValidationFailed
from almlight.modules.items.revisions import next_revision
from almlight.modules.projects.metamodel import ProjectTemplate, available_templates
from almlight.modules.variants import expressions


@pytest.mark.parametrize("label,expected", [("A", "B"), ("Y", "Z"), ("Z", "AA"), ("AZ", "BA"), ("ZZ", "AAA")])
def test_letter_revisions(label, expected):
    assert next_revision(label, "letters") == expected


def test_number_revisions():
    assert next_revision("9", "numbers") == "10"


@pytest.mark.parametrize("expr,selected,result", [
    ("A", {"A"}, True),
    ("A and B", {"A"}, False),
    ("A or B", {"B"}, True),
    ("not A", set(), True),
    ("A && (B || !C)", {"A", "C"}, False),
    ("A AND (B OR NOT C)", {"A"}, True),
    ("true", set(), True),
    ("false or A", {"A"}, True),
])
def test_expression_evaluation(expr, selected, result):
    assert expressions.applies(expr, selected) is result


@pytest.mark.parametrize("bad", ["A and", "(A or B", "A B", "and A", "A or )", "A $ B", "1A"])
def test_expression_syntax_errors(bad):
    with pytest.raises(ValidationFailed):
        expressions.parse(bad)


def test_expression_identifiers_and_empty():
    assert expressions.identifiers(expressions.parse("A and (B or not C)")) == {"A", "B", "C"}
    assert expressions.normalize("   ") is None
    assert expressions.applies(None, set()) is True


def test_shipped_templates_are_valid():
    templates = available_templates()
    se = templates["systems_engineering"]
    assert se.item_type("system_requirement").workflow == "requirement"
    assert se.workflow("change_order").transition("release").effects == ["release_affected_items"]
    assert "contains" in se.structural_link_types()
    assert se.semantics.affects_link == "affects"


def _minimal(**overrides):
    data = {
        "key": "t", "label": "T",
        "item_types": [{"key": "req", "label": "Req", "prefix": "R", "workflow": "wf"}],
        "workflows": [{"key": "wf", "label": "WF", "states": [{"key": "draft", "label": "Draft", "initial": True}]}],
    }
    data.update(overrides)
    return data


def test_template_validation_errors():
    ProjectTemplate.model_validate(_minimal())
    with pytest.raises(ValueError):
        ProjectTemplate.model_validate(_minimal(workflows=[]))  # unknown workflow
    with pytest.raises(ValueError):
        ProjectTemplate.model_validate(_minimal(item_types=[
            {"key": "a", "label": "A", "prefix": "X"}, {"key": "b", "label": "B", "prefix": "X"}]))
    with pytest.raises(ValueError):
        ProjectTemplate.model_validate(_minimal(link_types=[
            {"key": "l", "label": "l", "reverse_label": "l", "sources": ["ghost"]}]))
    with pytest.raises(ValueError):
        ProjectTemplate.model_validate(_minimal(workflows=[{"key": "wf", "label": "WF", "states": [
            {"key": "a", "label": "A", "initial": True}], "transitions": [
            {"key": "t", "label": "T", "from": ["a"], "to": "missing"}]}]))
    with pytest.raises(ValueError):
        ProjectTemplate.model_validate(_minimal(workflows=[{"key": "wf", "label": "WF", "states": [
            {"key": "a", "label": "A", "initial": True}], "transitions": [
            {"key": "t", "label": "T", "from": ["a"], "to": "a", "guards": ["teleport"]}]}]))
    with pytest.raises(ValueError):
        ProjectTemplate.model_validate(_minimal(item_types=[
            {"key": "req", "label": "Req", "prefix": "R", "fields": [{"key": "e", "label": "E", "type": "enum"}]}]))


@pytest.mark.parametrize("body,expected", [
    ("@rita please check", ["rita"]),
    ("cc @Rita.M and @max-2, thanks @rita.", ["rita.m", "max-2", "rita"]),
    ("ask @alex@example.com.", ["alex@example.com"]),
    ("mail me at alex@example.com", []),
    ("@x is too short", []),
])
def test_mentions(body, expected):
    from almlight.modules.notifications.service import mentions

    assert mentions(body) == expected


def test_working_day_calendar_and_dependency_rules():
    from datetime import date

    from almlight.modules.planning import schedule as sc

    fri, mon = date(2026, 11, 6), date(2026, 11, 9)
    assert sc.add_workdays(fri, 1) == mon and sc.add_workdays(mon, -1) == fri and sc.add_workdays(fri, 0) == fri
    assert sc.workdays(fri, mon) == 1 and sc.workdays(mon, fri) == -1 and sc.span(date(2026, 11, 2), fri) == 5
    nodes = {"P": {"kind": "task", "_start": date(2026, 11, 2), "_due": fri},
             "S": {"kind": "task", "_start": mon, "_due": date(2026, 11, 13)},
             "M": {"kind": "milestone", "_start": fri, "_due": fri},
             "M2": {"kind": "milestone", "_start": date(2026, 11, 13), "_due": date(2026, 11, 13)}}
    assert not sc.violated(nodes, sc.Dep("P", "S"))                          # Monday after a Friday finish
    assert sc.violated(nodes, sc.Dep("P", "S", lag=1))                        # one day waiting time
    assert not sc.violated(nodes, sc.Dep("P", "M"))                           # milestone on the finish day
    assert sc.violated(nodes, sc.Dep("P", "S", "ss", lag=6))
    assert not sc.violated(nodes, sc.Dep("P", "S", "ff", lag=5))
    assert sc.violated(nodes, sc.Dep("P", "S", "ff", lag=6))
    assert sc.required_shift(nodes, sc.Dep("P", "S", lag=1)) == 1
    deps = [sc.Dep("P", "S", lag=1), sc.Dep("S", "M2")]
    sc.slack(nodes, deps, {})
    assert nodes["P"]["slack"] == -1 and nodes["S"]["slack"] == 0 and nodes["M2"]["slack"] == 0
    moved = sc.forward(nodes, deps, {"S", "M2"})
    assert moved["S"] == (date(2026, 11, 10), date(2026, 11, 16)) and moved["M2"][1] == date(2026, 11, 16)
    assert sc.topological({"a": 1, "b": 1}, [sc.Dep("a", "b"), sc.Dep("b", "a")]) == []
