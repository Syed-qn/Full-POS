from app.ordering.service import parse_detail_includes, _detail_wants


def test_parse_detail_includes_none_means_all_sections():
    assert parse_detail_includes(None) is None
    assert parse_detail_includes("all") is None
    assert parse_detail_includes("*") is None


def test_parse_detail_includes_always_adds_overview():
    assert parse_detail_includes("overview") == frozenset({"overview"})
    assert parse_detail_includes("timeline,chat") == frozenset(
        {"overview", "timeline", "chat"}
    )


def test_detail_wants_respects_include_set():
    includes = parse_detail_includes("overview,chat")
    assert _detail_wants("chat", includes) is True
    assert _detail_wants("timeline", includes) is False
    assert _detail_wants("timeline", None) is True