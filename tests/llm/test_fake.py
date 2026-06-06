from app.llm.fake import FakeExtractor
from app.llm.port import DishDraft, UploadedFile


async def test_fake_extractor_returns_drafts():
    fake = FakeExtractor()
    files = [UploadedFile(filename="menu.jpg", content=b"\xff\xd8", mime="image/jpeg")]
    drafts = await fake.extract_menu(files)
    assert len(drafts) >= 2
    assert all(isinstance(d, DishDraft) for d in drafts)
    assert drafts[0].dish_number == 110
    assert drafts[0].name == "Chicken Biryani"


async def test_fake_extractor_canned_override():
    canned = [DishDraft(dish_number=1, name="Tea", price_aed="2.00")]
    fake = FakeExtractor(canned=canned)
    drafts = await fake.extract_menu([])
    assert drafts == canned
