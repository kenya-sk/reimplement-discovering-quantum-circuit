import os
from pathlib import Path

import pytest

from qdiscover.credentials import API_KEY_VARIABLES, load_api_key


@pytest.mark.parametrize("variable", sorted(API_KEY_VARIABLES))
@pytest.mark.parametrize(
    "assignment",
    ["{key}=dummy-value", 'export {key} = "dummy-value" # comment', "{key}='dummy-value'"],
)
def test_loads_selected_key_only(
    variable: str, assignment: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("UNRELATED_SETTING", raising=False)
    source = tmp_path / "credentials.txt"
    source.write_text(
        "# credentials\nUNRELATED_SETTING=ignored\n" + assignment.format(key=variable)
    )
    load_api_key(variable, source)
    assert os.environ[variable] == "dummy-value"
    assert "UNRELATED_SETTING" not in os.environ


def test_environment_takes_precedence_without_reading_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "environment-value")
    # A directory cannot be read as a file; existing credentials skip file access entirely.
    load_api_key("ANTHROPIC_API_KEY", tmp_path)
    assert os.environ["ANTHROPIC_API_KEY"] == "environment-value"


def test_missing_file_and_invalid_quoting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    source = tmp_path / "credentials.txt"
    load_api_key("ANTHROPIC_API_KEY", source)
    assert "ANTHROPIC_API_KEY" not in os.environ
    source.write_text('ANTHROPIC_API_KEY="secret-placeholder')
    with pytest.raises(ValueError) as error:
        load_api_key("ANTHROPIC_API_KEY", source)
    assert "secret-placeholder" not in str(error.value)
    assert "ANTHROPIC_API_KEY" not in os.environ
