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
