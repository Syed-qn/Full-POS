"""Opening hours are dynamic: saved via the settings PATCH and read back by the
bot's hours grounding helper — no hardcoded timings."""
import pytest
from pydantic import ValidationError

from app.conversation.engine import _hours_info
from app.identity.schemas import SettingsPatch


class _R:
    """Minimal stand-in for a Restaurant with a settings dict."""

    def __init__(self, settings):
        self.settings = settings


def test_settings_patch_accepts_valid_open_hours():
    p = SettingsPatch(open_hours={"tz": "Asia/Dubai", "days": {"0": ["10:00", "23:00"]}})
    assert p.open_hours["days"]["0"] == ["10:00", "23:00"]


@pytest.mark.parametrize("bad", [
    {"days": {"7": ["10:00", "23:00"]}},          # invalid weekday
    {"days": {"0": ["23:00", "10:00"]}},          # close before open
    {"days": {"0": ["10:00"]}},                   # not a pair
    {"days": {"0": ["25:00", "26:00"]}},          # invalid time
])
def test_settings_patch_rejects_bad_open_hours(bad):
    with pytest.raises(ValidationError):
        SettingsPatch(open_hours=bad)


def test_hours_info_unconfigured_forbids_inventing_times():
    info = _hours_info(_R({}))
    assert "do NOT state specific" in info


def test_hours_info_recites_configured_schedule():
    info = _hours_info(_R({"open_hours": {"tz": "Asia/Dubai", "days": {
        "0": ["10:00", "23:00"], "1": ["10:00", "23:00"],
    }}}))
    # Monday window is recited; an unconfigured day reads as closed.
    assert "Mon 10:00 AM–11:00 PM" in info
    assert "Wed closed" in info
