def test_engine_and_service_import():
    # F19 regression: engine.py calls set_item_note which must exist in service.py
    import app.conversation.engine  # noqa: F401
    from app.ordering.service import set_item_note  # noqa: F401
    assert callable(set_item_note)
