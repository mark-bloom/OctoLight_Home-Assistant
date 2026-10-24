import pytest

from octoprint_octolightHA.ha import HomeAssistantError
from octoprint_octolightHA.lighting import brightness, capabilities, light_attributes, rgb


@pytest.mark.parametrize(
    "mode,color,dim",
    [
        ("onoff", False, False),
        ("brightness", False, True),
        ("color_temp", False, True),
        ("hs", True, True),
        ("xy", True, True),
        ("rgbw", True, True),
        ("rgbww", True, True),
    ],
)
def test_color_modes(mode, color, dim):
    result = capabilities("light.printer", {"supported_color_modes": [mode]})
    assert result["color"] is color
    assert result["brightness"] is dim


def test_switch_never_receives_light_attributes():
    supported = capabilities("switch.printer", {"supported_features": 255})
    assert light_attributes({"brightness": 100, "color": "#ffffff"}, supported, strict=False) == {}
    with pytest.raises(HomeAssistantError, match="does not support"):
        light_attributes({"color": "#ffffff"}, supported)


def test_color_and_brightness_payload():
    assert rgb("#ff0080") == [255, 0, 128]
    assert light_attributes(
        {"color": "#ff0080", "brightness": "75", "flash": "short"},
        dict(color=True, brightness=True, flash=True),
    ) == {"rgb_color": [255, 0, 128], "brightness_pct": 75, "flash": "short"}


@pytest.mark.parametrize("value", [0, 101, -1, "no", None, True, float("nan"), float("inf")])
def test_invalid_brightness(value):
    with pytest.raises(HomeAssistantError):
        brightness(value)


@pytest.mark.parametrize("value", ["red", "fff", "#ggffff", "#ffffff00", None])
def test_invalid_color(value):
    with pytest.raises(HomeAssistantError):
        rgb(value)


@pytest.mark.parametrize(
    "attributes",
    [
        {"supported_color_modes": "rgb"},
        {"supported_color_modes": [{}]},
        {"supported_features": None},
    ],
)
def test_malformed_capabilities_are_reported(attributes):
    with pytest.raises(HomeAssistantError):
        capabilities("light.printer", attributes)
