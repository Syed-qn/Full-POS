from app.config import get_settings
from app.llm.fake import FakeExtractor
from app.llm.port import MenuExtractor


def get_menu_extractor() -> MenuExtractor:
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeExtractor

        return ClaudeExtractor()
    return FakeExtractor()
