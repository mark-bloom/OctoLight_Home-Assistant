"""Capability detection and validation shared by manual and automatic lighting."""
import re

from .ha import HomeAssistantError

COLOR_MODES = {"hs", "xy", "rgb", "rgbw", "rgbww"}


def capabilities(entity_id, attributes):
    if not entity_id.startswith("light."):
        return dict(brightness=False, color=False, flash=False)
    modes = set(attributes.get("supported_color_modes") or [])
    features = attributes.get("supported_features", 0)
    return dict(
        brightness=bool(modes - {"onoff", "unknown"}) if modes else bool(features & 1),
        color=bool(modes & COLOR_MODES) if modes else bool(features & 16),
        flash=bool(features & 8),
    )


def rgb(hex_color):
    if not isinstance(hex_color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", hex_color):
        raise HomeAssistantError("Choose a colour in #RRGGBB format.")
    return [int(hex_color[index:index + 2], 16) for index in (1, 3, 5)]


def brightness(value):
    if isinstance(value, bool):
        raise HomeAssistantError("Brightness must be a number from 1 to 100.")
    try:
        result = float(value)
        if not 1 <= result <= 100:
            raise ValueError
    except (TypeError, ValueError):
        raise HomeAssistantError("Brightness must be a number from 1 to 100.") from None
    return result


def light_attributes(values, supported, strict=True):
    result = {}
    for key in values:
        if key not in ("brightness", "color", "flash"):
            raise HomeAssistantError("Unsupported light attribute.")
        if not supported.get(key):
            if strict:
                raise HomeAssistantError("This entity does not support {}.".format(key))
            continue
        if key == "brightness":
            result["brightness_pct"] = brightness(values[key])
        elif key == "color":
            result["rgb_color"] = rgb(values[key])
        elif values[key] == "short":
            result["flash"] = "short"
        else:
            raise HomeAssistantError("Only a short flash is supported.")
    return result
