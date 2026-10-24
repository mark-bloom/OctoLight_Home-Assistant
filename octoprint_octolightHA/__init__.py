"""OctoPrint controls and print automation for Home Assistant lights."""

from concurrent.futures import ThreadPoolExecutor
from threading import RLock, Timer

import flask
import octoprint.plugin
from octoprint.access.permissions import Permissions
from octoprint.events import Events

from .ha import HomeAssistant, HomeAssistantError, validate_entity, validate_state
from .lighting import brightness, capabilities, light_attributes, rgb


class OctoLightHAPlugin(
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.ShutdownPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.SimpleApiPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.EventHandlerPlugin,
):
    def __init__(self):
        self.config = {}
        self.states = {}
        self._lock = RLock()
        self._timer_lock = RLock()
        self._poll_timer = None
        self._idle_timers = {}
        self._generation = 0
        self._print_generation = 0
        self._running = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="octolight")

    def get_settings_defaults(self):
        return dict(
            address="",
            api_key="",
            entity_id="",
            verify_certificate=True,
            turnOnPrintStart=False,
            turnOffPrintEnd=False,
            turnOffPrintDelay=0,
            turnOffPrintFailure=False,
            turnOffPrintCancellation=False,
            pollInterval=10,
            icon="lightbulb",
            additionalEntities=[],
            applyBrightness=False,
            brightness=100,
            applyColor=False,
            color="#ffffff",
            statusColorsEnabled=False,
            alertFlash=False,
            enableGcode=False,
            printingColor="#ffffff",
            pausedColor="#ff9900",
            successColor="#00ff00",
            errorColor="#ff0000",
            cancelledColor="#ff6600",
        )

    def get_settings_restricted_paths(self):
        return {"admin": [["api_key"]]}

    def get_settings_version(self):
        return 1

    def on_settings_migrate(self, target, current):
        # Older defaults disabled verification, so an absent stored key can mean
        # an existing self-signed installation. Preserve it only during upgrade.
        if (
            current is None
            and self._settings.get(["address"])
            and not self._settings.has(["verify_certificate"], incl_defaults=False)
        ):
            self._settings.set_boolean(["verify_certificate"], False)

    def on_settings_initialized(self):
        self.reload_settings()

    def reload_settings(self):
        with self._lock:
            defaults = self.get_settings_defaults()
            config = {}
            for key, default in defaults.items():
                getter = (
                    self._settings.get_boolean if isinstance(default, bool) else self._settings.get
                )
                value = getter([key])
                config[key] = default if value is None else value
            config["address"] = config["address"].strip().rstrip("/")
            self.config = config
            self.states = {}
            self._generation += 1
            self._cancel_timers()
            if self._running:
                self._schedule_poll(0)

    def on_settings_save(self, data):
        try:
            data = self._validated_settings(data)
        except HomeAssistantError as error:
            # OctoPrint catches settings-save exceptions and returns 200 anyway.
            # Publish an explicit UI error and leave the previous configuration intact.
            self._plugin_manager.send_plugin_message(
                self._identifier, dict(settingsError=str(error))
            )
            self._logger.warning("Settings not saved: %s", error)
            return
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self.reload_settings()

    def _validated_settings(self, data):
        merged = dict(self.config, **data)
        if merged.get("address") or merged.get("api_key"):
            HomeAssistant(merged["address"], merged["api_key"], merged["verify_certificate"])
        if merged.get("entity_id"):
            value = merged["entity_id"]
            validate_entity(value.strip() if isinstance(value, str) else value)
        self._validate_settings(merged)
        data = dict(data)
        for key in ("address", "entity_id"):
            if key in data:
                if not isinstance(data[key], str):
                    raise HomeAssistantError("Address and entity ID must be text.")
                data[key] = data[key].strip()
        if "address" in data:
            data["address"] = data["address"].rstrip("/")
        if "additionalEntities" in data:
            row_defaults = {
                key: value
                for key, value in self.get_settings_defaults().items()
                if key
                in (
                    "icon",
                    "turnOnPrintStart",
                    "turnOffPrintEnd",
                    "turnOffPrintDelay",
                    "turnOffPrintFailure",
                    "turnOffPrintCancellation",
                )
            }
            data["additionalEntities"] = [
                dict(row_defaults, **entity) for entity in data["additionalEntities"]
            ]
        return data

    @staticmethod
    def _validate_settings(config):
        for key in (
            "verify_certificate",
            "turnOnPrintStart",
            "turnOffPrintEnd",
            "turnOffPrintFailure",
            "turnOffPrintCancellation",
            "applyBrightness",
            "applyColor",
            "statusColorsEnabled",
            "alertFlash",
            "enableGcode",
        ):
            if key in config and not isinstance(config[key], bool):
                raise HomeAssistantError("Checkbox settings must be enabled or disabled.")
        brightness(config.get("brightness", 100))
        for key in (
            "color",
            "printingColor",
            "pausedColor",
            "successColor",
            "errorColor",
            "cancelledColor",
        ):
            rgb(config.get(key, "#ffffff"))
        try:
            interval = float(config["pollInterval"])
            delay = float(config["turnOffPrintDelay"])
            if not 5 <= interval <= 3600 or not 0 <= delay <= 1440:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise HomeAssistantError(
                "Polling must be 5–3600 seconds; shutoff delay must be 0–1440 minutes."
            ) from None
        if config.get("icon") not in ("lightbulb", "power-off"):
            raise HomeAssistantError("Choose the lightbulb or power icon.")
        extras = config.get("additionalEntities", [])
        if not isinstance(extras, list) or len(extras) > 20:
            raise HomeAssistantError("Configure at most 20 additional entities.")
        ids = {config.get("entity_id")}
        for entity in extras:
            if not isinstance(entity, dict):
                raise HomeAssistantError("Invalid additional entity configuration.")
            entity_id = validate_entity(entity.get("entity_id"))
            if entity_id in ids:
                raise HomeAssistantError("Each configured entity must be unique.")
            ids.add(entity_id)
            if entity.get("icon", "lightbulb") not in ("lightbulb", "power-off"):
                raise HomeAssistantError("Choose the lightbulb or power icon.")
            # Validate per-entity overrides with the same limits as the primary.
            override = dict(config, **entity)
            override["additionalEntities"] = []
            OctoLightHAPlugin._validate_settings(override)

    def get_template_configs(self):
        return [
            dict(type="navbar", custom_bindings=True),
            dict(type="settings", custom_bindings=True),
        ]

    def is_template_autoescaped(self):
        return True

    def get_assets(self):
        return dict(js=["js/octolightHA.js"], css=["css/octolightHA.css"])

    def _client(self, config=None):
        config = self.config if config is None else config
        return HomeAssistant(
            config.get("address"), config.get("api_key"), config.get("verify_certificate", True)
        )

    def _entities(self, config=None):
        config = self.config if config is None else config
        entities = []
        if config.get("entity_id"):
            entities.append(
                dict(entity_id=config["entity_id"], icon=config.get("icon", "lightbulb"))
            )
        return entities + config.get("additionalEntities", [])

    def _entity(self, entity_id=None):
        entity_id = entity_id or self.config.get("entity_id")
        for entity in self._entities():
            if entity["entity_id"] == entity_id:
                return entity
        raise HomeAssistantError(
            "Choose and save a Home Assistant entity in plugin settings first."
        )

    def _snapshot(self):
        config, states = self.config, self.states.copy()
        primary = states.get(config.get("entity_id"), {})
        entities = []
        for entity in self._entities(config):
            entities.append(
                dict(
                    name=entity["entity_id"],
                    isLightOn=None,
                    available=False,
                    error=None,
                    attributes={},
                    capabilities={},
                )
                | entity
                | states.get(entity["entity_id"], {})
            )
        return dict(
            state=primary.get("isLightOn"), isLightOn=primary.get("isLightOn"), entities=entities
        )

    def _publish(self):
        self._plugin_manager.send_plugin_message(self._identifier, self._snapshot())

    def _refresh(self, entity_id, raw=None):
        try:
            raw = self._client().state(entity_id) if raw is None else validate_state(raw)
            state = raw["state"]
            attributes = raw.get("attributes", {})
            item = dict(
                isLightOn={"on": True, "off": False}.get(state),
                available=state in ("on", "off"),
                error=None,
                name=attributes.get("friendly_name", entity_id),
                attributes={
                    key: attributes[key]
                    for key in (
                        "brightness",
                        "rgb_color",
                        "hs_color",
                        "supported_color_modes",
                        "supported_features",
                    )
                    if key in attributes
                },
            )
            item["capabilities"] = capabilities(entity_id, attributes)
        except HomeAssistantError as error:
            item = dict(isLightOn=None, available=False, error=str(error), attributes={})
        self.states[entity_id] = item
        return item

    def _poll(self, generation):
        with self._lock:
            if not self._running or generation != self._generation:
                return
            previous = self._snapshot()
            entities = self._entities()
            if entities:
                try:
                    # One request per poll, regardless of configured entity count.
                    remote = {item["entity_id"]: item for item in self._client().entities()}
                    for entity in entities:
                        entity_id = entity["entity_id"]
                        if entity_id in remote:
                            self._refresh(entity_id, remote[entity_id])
                        else:
                            self.states[entity_id] = dict(
                                isLightOn=None,
                                available=False,
                                error="Entity not found in Home Assistant. Search and select its complete ID.",
                                attributes={},
                            )
                except HomeAssistantError as error:
                    for entity in entities:
                        self.states[entity["entity_id"]] = dict(
                            isLightOn=None, available=False, error=str(error), attributes={}
                        )
            if previous != self._snapshot():
                self._publish()
            if self._running and generation == self._generation:
                self._schedule_poll()

    def _schedule_poll(self, delay=None):
        with self._timer_lock:
            if not self._running:
                return
            if self._poll_timer:
                self._poll_timer.cancel()
            try:
                interval = max(5, min(3600, float(self.config.get("pollInterval", 10))))
            except (ValueError, TypeError):
                interval = 10
            self._poll_timer = Timer(
                interval if delay is None else delay, self._poll, (self._generation,)
            )
            self._poll_timer.daemon = True
            self._poll_timer.start()

    def on_after_startup(self):
        with self._lock:
            self._running = True
            self._schedule_poll(0)
        self._logger.info("OctoLight Home Assistant started")

    def _cancel_idle(self, entity_id=None):
        with self._timer_lock:
            ids = [entity_id] if entity_id else list(self._idle_timers)
            for key in ids:
                timer = self._idle_timers.pop(key, None)
                if timer:
                    timer[0].cancel()

    def _cancel_timers(self):
        self._cancel_idle()
        if self._poll_timer:
            self._poll_timer.cancel()
            self._poll_timer = None

    def on_shutdown(self):
        with self._timer_lock:
            self._running = False
            self._generation += 1
            self._cancel_timers()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _control(self, action, entity_id=None, attributes=None, manual=True):
        with self._lock:
            entity = self._entity(entity_id)
            entity_id = entity["entity_id"]
            config = dict(self.config, **entity)
            # Read before toggling so turn-on defaults are applied consistently.
            if (
                action == "toggle"
                or attributes
                or (
                    action == "turn_on"
                    and (config.get("applyBrightness") or config.get("applyColor"))
                )
            ):
                state = self._refresh(entity_id)
                if not state["available"]:
                    self._publish()
                    raise HomeAssistantError(
                        state.get("error") or "The Home Assistant entity is unavailable."
                    )
                if action == "toggle":
                    action = "turn_off" if state["isLightOn"] else "turn_on"
            values = {}
            if action == "turn_on":
                if config.get("applyBrightness"):
                    values["brightness"] = config["brightness"]
                if config.get("applyColor"):
                    values["color"] = config["color"]
            supported = self.states.get(entity_id, {}).get("capabilities", {})
            payload = light_attributes(values, supported, strict=False)
            if attributes:
                payload.update(light_attributes(attributes, supported))
            if manual:
                self._cancel_idle(entity_id)
            try:
                self._client().service(entity_id, action, **payload)
            except HomeAssistantError as error:
                self.states[entity_id] = dict(
                    isLightOn=None, available=False, error=str(error), attributes={}
                )
                self._publish()
                raise
            self._refresh(entity_id)
            self._publish()
            return self._snapshot()

    def is_api_protected(self):
        return True

    def get_api_commands(self):
        return dict(toggle=[], turnOn=[], turnOff=[], setLight=[], discover=[], test=[])

    def on_api_get(self, request):
        if not Permissions.STATUS.can():
            flask.abort(403)
        if request.args.get("action", "getState") != "getState":
            return flask.jsonify(error="Use POST commands for light control."), 405
        return flask.jsonify(self._snapshot())

    def on_api_command(self, command, data):
        if command in ("discover", "test"):
            if not Permissions.SETTINGS.can():
                flask.abort(403)
        elif not Permissions.CONTROL.can():
            flask.abort(403)
        try:
            with self._lock:
                if command in ("discover", "test"):
                    # Unsaved connection fields allow setup without a save/reload cycle.
                    config = dict(self.config)
                    for key in ("address", "api_key", "verify_certificate"):
                        if key in data:
                            config[key] = data[key]
                    client = self._client(config)
                    if command == "test":
                        raw = client.state(data.get("entity_id", self.config.get("entity_id")))
                        return flask.jsonify(
                            state=raw["state"], attributes=raw.get("attributes", {})
                        )
                    entities = client.entities()
                    return flask.jsonify(
                        entities=[
                            dict(
                                entity_id=e["entity_id"],
                                name=e.get("attributes", {}).get("friendly_name", e["entity_id"]),
                                state=e.get("state"),
                            )
                            for e in entities
                        ]
                    )
                actions = dict(
                    toggle="toggle", turnOn="turn_on", turnOff="turn_off", setLight="turn_on"
                )
                if command not in actions:
                    return flask.jsonify(error="Unknown command."), 400
                attributes = {
                    key: data[key] for key in ("brightness", "color", "flash") if key in data
                }
                if command != "setLight" and attributes:
                    raise HomeAssistantError("Use setLight to change brightness or colour.")
                return flask.jsonify(
                    self._control(actions[command], data.get("entity_id"), attributes)
                )
        except HomeAssistantError as error:
            return flask.jsonify(error=str(error)), 400

    def on_event(self, event, payload):
        if event == Events.CLIENT_OPENED:
            self._publish()
            return
        # Never wait for Home Assistant I/O on OctoPrint's event dispatch thread.
        with self._timer_lock:
            # Cancel synchronously even when print-start lighting is disabled.
            if event == Events.PRINT_STARTED:
                self._print_generation += 1
                self._cancel_idle()
            if self._running and event in (
                Events.PRINT_STARTED,
                Events.PRINT_DONE,
                Events.PRINT_PAUSED,
                Events.PRINT_RESUMED,
                Events.ERROR,
                Events.PRINT_FAILED,
                Events.PRINT_CANCELLED,
            ):
                self._executor.submit(
                    self._handle_print_event, event, self._generation, self._print_generation
                )

    def _handle_print_event(self, event, generation, print_generation):
        with self._lock:
            if (
                not self._running
                or generation != self._generation
                or print_generation != self._print_generation
            ):
                return
            for entity in self._entities():
                if not self._running or print_generation != self._print_generation:
                    return
                config = dict(self.config, **entity)
                entity_id = entity["entity_id"]
                try:
                    themed = False
                    turn_off = (event == Events.PRINT_FAILED and config["turnOffPrintFailure"]) or (
                        event == Events.PRINT_CANCELLED and config["turnOffPrintCancellation"]
                    )
                    if (
                        config.get("statusColorsEnabled")
                        and entity_id.startswith("light.")
                        and not turn_off
                    ):
                        themed = self._status_color(event, entity_id, config)
                    if event == Events.PRINT_STARTED and config["turnOnPrintStart"]:
                        if not themed:
                            self._control("turn_on", entity_id, manual=False)
                    elif event == Events.PRINT_DONE and config["turnOffPrintEnd"]:
                        self._cancel_idle(entity_id)
                        delay = max(0, float(config["turnOffPrintDelay"])) * 60
                        if delay == 0:
                            if not self._printer.is_printing() and not self._printer.is_paused():
                                self._control("turn_off", entity_id, manual=False)
                        else:
                            token = object()
                            timer = Timer(delay, self._idle_off, (entity_id, generation, token))
                            timer.daemon = True
                            with self._timer_lock:
                                if print_generation == self._print_generation and self._running:
                                    self._idle_timers[entity_id] = (timer, token)
                                    timer.start()
                    elif turn_off:
                        self._cancel_idle(entity_id)
                        self._control("turn_off", entity_id, manual=False)
                except (HomeAssistantError, ValueError, TypeError) as error:
                    self._logger.warning("Print lighting failed: %s", error)

    def _status_color(self, event, entity_id, config):
        key = {
            Events.PRINT_STARTED: "printingColor",
            Events.PRINT_RESUMED: "printingColor",
            Events.PRINT_PAUSED: "pausedColor",
            Events.PRINT_DONE: "successColor",
            Events.PRINT_FAILED: "errorColor",
            Events.ERROR: "errorColor",
            Events.PRINT_CANCELLED: "cancelledColor",
        }.get(event)
        if not key:
            return False
        state = self._refresh(entity_id)
        supported = state.get("capabilities", {})
        if not state["available"] or not supported.get("color"):
            return False
        values = {"color": config[key]}
        if (
            config.get("alertFlash")
            and supported.get("flash")
            and event in (Events.ERROR, Events.PRINT_FAILED)
        ):
            values["flash"] = "short"
        self._control("turn_on", entity_id, values, manual=False)
        return True

    def _idle_off(self, entity_id, generation, token):
        with self._lock:
            with self._timer_lock:
                if (
                    not self._running
                    or generation != self._generation
                    or self._idle_timers.get(entity_id, (None, None))[1] is not token
                ):
                    return
                self._idle_timers.pop(entity_id, None)
            # A new print must never be darkened by a previous print timer.
            if self._printer.is_printing() or self._printer.is_paused():
                return
            try:
                self._control("turn_off", entity_id, manual=False)
            except HomeAssistantError as error:
                self._logger.warning("Delayed lighting failed: %s", error)

    def get_update_information(self):
        return dict(
            octolightHA=dict(
                displayName="OctoLight Home Assistant",
                displayVersion=self._plugin_version,
                type="github_release",
                user="mark-bloom",
                repo="OctoLight_Home-Assistant",
                current=self._plugin_version,
                pip="https://github.com/mark-bloom/OctoLight_Home-Assistant/archive/{target_version}.zip",
            )
        )

    def process_atcommand(self, comm, phase, command, parameters, tags=None, *args, **kwargs):
        """Opt-in host commands; no firmware M-code is intercepted or forwarded."""
        if command != "OCTOLIGHT":
            return
        with self._timer_lock:
            if not self._running or not self.config.get("enableGcode"):
                return
            parts = parameters.strip().split()
            actions = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}
            if not 1 <= len(parts) <= 2 or parts[0].lower() not in actions:
                self._logger.warning("Use @OCTOLIGHT on|off|toggle [configured_entity_id]")
                return
            try:
                entity_id = self._entity(parts[1] if len(parts) == 2 else None)["entity_id"]
            except HomeAssistantError as error:
                self._logger.warning("Lighting command rejected: %s", error)
                return
            self._executor.submit(
                self._queued_control, actions[parts[0].lower()], entity_id, self._generation
            )

    def _queued_control(self, action, entity_id, generation):
        with self._lock:
            if not self._running or generation != self._generation:
                return
            try:
                self._control(action, entity_id)
            except HomeAssistantError as error:
                self._logger.warning("Lighting command failed: %s", error)


__plugin_name__ = "OctoLight Home Assistant"
__plugin_pythoncompat__ = ">=3.9,<4"


def __plugin_load__():
    global __plugin_implementation__, __plugin_hooks__
    __plugin_implementation__ = OctoLightHAPlugin()
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.comm.protocol.atcommand.queuing": __plugin_implementation__.process_atcommand,
    }
