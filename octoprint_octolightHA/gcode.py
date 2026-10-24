"""Parse opt-in @OCTOLIGHT host commands without performing network I/O."""

from .ha import HomeAssistantError, validate_entity
from .lighting import brightness, rgb


def parse_atcommand(parameters):
    parts = parameters.split(";", 1)[0].split()
    actions = {"on": "turn_on", "off": "turn_off", "toggle": "toggle", "set": "turn_on"}
    if not parts or parts[0].lower() not in actions:
        raise HomeAssistantError(
            "Use @OCTOLIGHT on|off|toggle|set [entity_id] [brightness=75 color=#ff8000 flash=short]."
        )
    verb = parts[0].lower()
    entity_id = None
    attributes = {}
    for part in parts[1:]:
        if "=" not in part:
            if entity_id is not None:
                raise HomeAssistantError("Specify at most one configured entity ID.")
            entity_id = validate_entity(part)
            continue
        key, value = part.split("=", 1)
        key = key.lower()
        if key not in ("brightness", "color", "flash") or key in attributes:
            raise HomeAssistantError("Specify brightness, color or flash once each.")
        if key == "brightness":
            value = brightness(value)
        elif key == "color":
            rgb(value)
        elif value != "short":
            raise HomeAssistantError("Only flash=short is supported.")
        attributes[key] = value
    if verb in ("off", "toggle") and attributes:
        raise HomeAssistantError("Appearance options require on or set.")
    if verb == "set" and not attributes:
        raise HomeAssistantError("Specify brightness=1–100, color=#RRGGBB or flash=short.")
    return actions[verb], entity_id, attributes
