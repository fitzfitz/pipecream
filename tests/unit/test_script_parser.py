import json
import sys

import pytest

from workers.step1_topic_script import DRY_RUN_SCRIPT, MAX_TITLE_CHARS, extract_script_json

VALID = {
    "title": "The Vanishing",
    "narration": "Nobody saw them leave. " * 5,
    "visual_prompts": ["Cinematic vertical 9:16 photo of a fog bank", "Cinematic vertical 9:16 empty pier"],
}


def test_module_import_does_not_load_mlx():
    assert "mlx_lm" not in sys.modules
    assert "mlx" not in sys.modules


def test_plain_json():
    assert extract_script_json(json.dumps(VALID))["title"] == "The Vanishing"


def test_json_markdown_block_is_stripped():
    raw = f"Sure! Here is your script:\n```json\n{json.dumps(VALID, indent=2)}\n```\nEnjoy!"
    data = extract_script_json(raw)
    assert data["visual_prompts"] == VALID["visual_prompts"]


def test_unlabelled_markdown_block():
    raw = f"```\n{json.dumps(VALID)}\n```"
    assert extract_script_json(raw)["narration"] == VALID["narration"].strip()


def test_surrounding_chatter_without_fence():
    raw = f"<|assistant|> Here you go {json.dumps(VALID)} hope it helps"
    assert extract_script_json(raw)["title"] == "The Vanishing"


def test_whitespace_is_trimmed():
    raw = json.dumps({**VALID, "title": "  Padded  ", "visual_prompts": ["  a  "]})
    data = extract_script_json(raw)
    assert data["title"] == "Padded"
    assert data["visual_prompts"] == ["a"]


def test_long_title_truncated_to_contract_limit():
    data = extract_script_json(json.dumps({**VALID, "title": "X" * 200}))
    assert len(data["title"]) == MAX_TITLE_CHARS


@pytest.mark.parametrize("missing", ["title", "narration", "visual_prompts"])
def test_missing_key_rejected(missing):
    bad = {k: v for k, v in VALID.items() if k != missing}
    with pytest.raises(ValueError, match=missing):
        extract_script_json(json.dumps(bad))


@pytest.mark.parametrize("override", [
    {"visual_prompts": []},
    {"visual_prompts": "not a list"},
    {"visual_prompts": ["ok", ""]},
    {"visual_prompts": ["ok", 3]},
    {"title": ""},
    {"narration": 42},
])
def test_invalid_schema_values_rejected(override):
    with pytest.raises(ValueError):
        extract_script_json(json.dumps({**VALID, **override}))


@pytest.mark.parametrize("raw", ["", "   ", "no json here at all", "```json\n```", "{not: valid json}"])
def test_unparseable_output_rejected(raw):
    with pytest.raises(ValueError):
        extract_script_json(raw)


def test_top_level_array_rejected():
    with pytest.raises(ValueError):
        extract_script_json("[1, 2, 3]")


def test_dry_run_script_satisfies_contract():
    data = extract_script_json(json.dumps(DRY_RUN_SCRIPT))
    assert len(data["visual_prompts"]) == 3
    assert all("9:16" in p for p in data["visual_prompts"])
