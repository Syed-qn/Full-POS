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


def test_settings_patch_accepts_batch_geometry():
    p = SettingsPatch(
        batch_proximity_km=2.5,
        batch_window_minutes=15,
        sla_buffer_per_order_minutes=6,
        batch_max_detour_km=1.0,
    )
    assert p.batch_proximity_km == 2.5
    assert p.batch_window_minutes == 15
    assert p.sla_buffer_per_order_minutes == 6
    assert p.batch_max_detour_km == 1.0


def test_settings_patch_allows_zero_detour_to_disable_corridor():
    assert SettingsPatch(batch_max_detour_km=0).batch_max_detour_km == 0


@pytest.mark.parametrize("bad", [
    {"batch_proximity_km": 0},     # must be > 0
    {"batch_proximity_km": 11},    # > 10 km
    {"batch_max_detour_km": -1},   # negative
    {"batch_max_detour_km": 11},   # > 10 km
    {"sla_buffer_per_order_minutes": 31},  # > 30
])
def test_settings_patch_rejects_bad_batch_geometry(bad):
    with pytest.raises(ValidationError):
        SettingsPatch(**bad)


def test_settings_patch_accepts_valid_todays_special():
    p = SettingsPatch(todays_special={
        "enabled": True, "template_id": 7, "lead_minutes": 20, "default_time": "9:05",
    })
    assert p.todays_special == {
        "enabled": True, "template_id": 7, "lead_minutes": 20, "default_time": "09:05",
    }


def test_settings_patch_todays_special_defaults_when_disabled():
    p = SettingsPatch(todays_special={"enabled": False})
    assert p.todays_special["enabled"] is False
    assert p.todays_special["template_id"] is None
    assert p.todays_special["default_time"] == "11:45"


@pytest.mark.parametrize("bad", [
    {"enabled": True},                                    # on without a template
    {"enabled": True, "template_id": 1, "lead_minutes": 999},   # lead out of range
    {"enabled": False, "default_time": "26:00"},          # invalid time
    {"enabled": "yes", "template_id": 1},                 # non-boolean enabled
])
def test_settings_patch_rejects_bad_todays_special(bad):
    with pytest.raises(ValidationError):
        SettingsPatch(todays_special=bad)


def test_hours_info_unconfigured_forbids_inventing_times():
    info = _hours_info(_R({}))
    assert "do NOT state specific" in info


def test_hours_info_recites_configured_schedule():
    info = _hours_info(_R({"open_hours": {"tz": "Asia/Dubai", "days": {
        "0": ["10:00", "23:00"], "1": ["10:00", "23:00"],
    }}}))
    # Monday window is recited; an unconfigured day reads as closed.
    assert "Mon 10:00 AM to 11:00 PM" in info
    assert "Wed closed" in info
