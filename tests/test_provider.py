import pytest

from qdiscover.llm import message_text, parse_json_object
from qdiscover.specification import parse_families


@pytest.mark.parametrize(
    "text", ['```json\n{"source": "pass"}\n```', '```json\n{"source": "pass"}```']
)
def test_fenced_json_and_truncation_are_handled(text: str) -> None:
    result = parse_json_object(message_text({"content": [{"type": "text", "text": text}]}))
    assert result["source"] == "pass"
    with pytest.raises(ValueError, match="truncated"):
        message_text({"stop_reason": "max_tokens"})


@pytest.mark.parametrize("text", ["[]", "```json\nnull\n```"])
def test_model_response_must_be_a_json_object(text: str) -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parse_json_object(text)


@pytest.mark.parametrize(
    "families",
    [
        [{"name": "same", "description": "a"}, {"name": "same", "description": "b"}],
        [{"name": "a", "description": "a"}, {"name": "b"}],
    ],
)
def test_algorithm_families_need_unique_names_and_descriptions(
    families: list[dict[str, str]],
) -> None:
    with pytest.raises(ValueError):
        parse_families({"families": families}, 2)
