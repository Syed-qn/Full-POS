"""context.txt prompt goldmine must exist and stay substantial."""

from app.llm.prompt_goldmine import GOLDMINE_PATH, goldmine_line_count, load_prompt_goldmine


def test_context_txt_exists():
    assert GOLDMINE_PATH.is_file(), "context.txt must not be deleted"


def test_context_txt_minimum_size():
    assert goldmine_line_count() >= 700, "context.txt should hold full prompt archive"


def test_context_txt_contains_master_template_sections():
    text = load_prompt_goldmine()
    for tag in ("[ROLE]", "[CONTEXT]", "[TASK]", "[CONSTRAINTS]", "[OUTPUT]"):
        assert tag in text
    assert "DO NOT DELETE" in text
    assert "ORDERING" in text or "_ORDERING" in text