import pytest

from octoprint_octolightHA.gcode import parse_atcommand
from octoprint_octolightHA.ha import HomeAssistantError


@pytest.mark.parametrize(
    "verb,action", [("on", "turn_on"), ("off", "turn_off"), ("toggle", "toggle")]
)
def test_basic_host_commands(verb, action):
    assert parse_atcommand(verb) == (action, None, {})
    assert parse_atcommand(verb + " switch.room") == (action, "switch.room", {})


def test_all_appearance_options_and_comment():
    assert parse_atcommand(
        "set light.printer brightness=75 color=#ff8000 flash=short ; orange"
    ) == ("turn_on", "light.printer", {"brightness": 75, "color": "#ff8000", "flash": "short"})


@pytest.mark.parametrize(
    "options,expected",
    [
        ("brightness=1", {"brightness": 1}),
        ("brightness=100", {"brightness": 100}),
        ("brightness=75.5", {"brightness": 75.5}),
        ("color=#000000", {"color": "#000000"}),
        ("flash=short", {"flash": "short"}),
    ],
)
def test_individual_appearance_options(options, expected):
    assert parse_atcommand("on " + options) == ("turn_on", None, expected)
    assert parse_atcommand("set " + options) == ("turn_on", None, expected)


@pytest.mark.parametrize(
    "command",
    [
        "",
        "unknown",
        "set",
        "on desk_lamp",
        "on light.a light.b",
        "off brightness=75",
        "toggle color=#ffffff",
        "set brightness=0",
        "set brightness=101",
        "set brightness=NaN",
        "set brightness=inf",
        "set brightness=no",
        "set color=red",
        "set color=#ffffff00",
        "set flash=long",
        "set flash=",
        "set brightness=75 brightness=80",
        "set color=#ffffff color=#000000",
        "set unknown=1",
        "set sensor.temperature color=#ffffff",
    ],
)
def test_rejects_invalid_commands(command):
    with pytest.raises(HomeAssistantError):
        parse_atcommand(command)
