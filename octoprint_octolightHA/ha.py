"""Small, bounded Home Assistant REST client. Never exposes response bodies/tokens."""

import re
from urllib.parse import urlsplit

import requests


class HomeAssistantError(Exception):
    """An actionable error safe to display to the user."""


ENTITY = re.compile(r"^(light|switch|input_boolean)\.[a-z0-9_]+$")


def validate_entity(entity_id):
    if not isinstance(entity_id, str) or not ENTITY.fullmatch(entity_id):
        raise HomeAssistantError(
            "Use a complete entity ID such as light.printer or switch.desk_lamp. "
            "Search Home Assistant to find it."
        )
    return entity_id


class HomeAssistant:
    def __init__(self, address, token, verify=True):
        self.address = (address or "").strip().rstrip("/")
        try:
            url = urlsplit(self.address)
            valid = url.scheme in ("http", "https") and url.hostname and url.port != 0
        except ValueError:
            valid = False
        if not valid or url.username or url.password or url.query or url.fragment:
            raise HomeAssistantError(
                "Enter a Home Assistant URL such as http://homeassistant.local:8123."
            )
        if not isinstance(token, str) or not token.strip():
            raise HomeAssistantError("Enter a Home Assistant long-lived access token.")
        self.token = token.strip()
        self.verify = verify

    def request(self, method, path, payload=None):
        try:
            response = requests.request(
                method,
                self.address + "/api/" + path,
                headers={"Authorization": "Bearer " + self.token},
                json=payload,
                verify=self.verify,
                timeout=(3.05, 10),
                allow_redirects=False,
            )
        except requests.exceptions.Timeout:
            raise HomeAssistantError(
                "Home Assistant timed out. Check its address and network."
            ) from None
        except requests.exceptions.SSLError:
            raise HomeAssistantError(
                "Home Assistant TLS certificate verification failed."
            ) from None
        except requests.exceptions.RequestException:
            raise HomeAssistantError(
                "Cannot connect to Home Assistant. Check the address and network."
            ) from None
        if response.status_code in (401, 403):
            raise HomeAssistantError("Home Assistant rejected the access token or its permissions.")
        if response.status_code == 404:
            raise HomeAssistantError(
                "Home Assistant entity or endpoint not found. Check the complete entity ID and address."
            )
        if not 200 <= response.status_code < 300:
            raise HomeAssistantError(
                "Home Assistant returned HTTP {}.".format(response.status_code)
            )
        try:
            return response.json()
        except ValueError:
            raise HomeAssistantError(
                "Home Assistant returned invalid JSON. Check the server address."
            ) from None

    def state(self, entity_id):
        data = self.request("GET", "states/" + validate_entity(entity_id))
        if not isinstance(data, dict) or data.get("state") not in (
            "on",
            "off",
            "unknown",
            "unavailable",
        ):
            raise HomeAssistantError("Home Assistant returned an invalid entity state.")
        if not isinstance(data.get("attributes", {}), dict):
            raise HomeAssistantError("Home Assistant returned invalid entity attributes.")
        return data

    def entities(self):
        data = self.request("GET", "states")
        if not isinstance(data, list):
            raise HomeAssistantError("Home Assistant returned an invalid entity list.")
        return [
            item
            for item in data
            if isinstance(item, dict)
            and isinstance(item.get("entity_id"), str)
            and ENTITY.fullmatch(item["entity_id"])
        ]

    def service(self, entity_id, action, **attributes):
        validate_entity(entity_id)
        if action not in ("turn_on", "turn_off", "toggle"):
            raise HomeAssistantError("Unsupported Home Assistant action.")
        # A successful service call can return [] while a physical device updates later.
        # Never infer a state by inverting a cached boolean or indexing this response.
        return self.request(
            "POST",
            "services/{}/{}".format(entity_id.split(".")[0], action),
            dict(entity_id=entity_id, **attributes),
        )
