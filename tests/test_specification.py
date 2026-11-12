from qdiscover.specification import task_context


def test_prompts_do_not_disclose_grader_or_discovered_source() -> None:
    context = task_context("coulomb-potential")
    assert "grader" not in context
    assert "oracle" not in context
    assert "## Specification" in context["specification"]
    assert "## 4. Discovered circuit" not in context["specification"]
    assert "Certified results" not in context["specification"]
