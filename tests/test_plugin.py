import logging
from unittest.mock import Mock, patch

import flask
import pytest
from octoprint.events import Events

from octoprint_octolightHA import OctoLightHAPlugin
from octoprint_octolightHA.ha import HomeAssistantError


@pytest.fixture
def plugin():
    p = OctoLightHAPlugin()
    p.config = dict(
        p.get_settings_defaults(),
        address="http://ha.local",
        api_key="secret",
        entity_id="light.printer",
    )
    p._identifier = "octolightHA"
    p._logger = logging.getLogger("test")
    p._plugin_manager = Mock()
    p._printer = Mock()
    p._printer.is_printing.return_value = False
    p._printer.is_paused.return_value = False
    p._running = True
    yield p
    p.on_shutdown()


@pytest.fixture
def app():
    return flask.Flask(__name__)


def test_get_is_read_only(plugin, app):
    with app.test_request_context("/"), patch("octoprint_octolightHA.Permissions") as permissions:
        permissions.STATUS.can.return_value = True
        with patch.object(plugin, "_client") as client:
            assert plugin.on_api_get(flask.request).json["state"] is None
            client.assert_not_called()
    with (
        app.test_request_context("/?action=toggle"),
        patch("octoprint_octolightHA.Permissions") as permissions,
    ):
        permissions.STATUS.can.return_value = True
        assert plugin.on_api_get(flask.request)[1] == 405


def test_commands_require_control(plugin, app):
    with app.test_request_context("/"), patch("octoprint_octolightHA.Permissions") as permissions:
        permissions.CONTROL.can.return_value = False
        permissions.SETTINGS.can.return_value = False
        with pytest.raises(Exception) as error:
            plugin.on_api_command("turnOff", {})
        assert error.value.code == 403


def test_discovery_requires_settings(plugin, app):
    with app.test_request_context("/"), patch("octoprint_octolightHA.Permissions") as permissions:
        permissions.CONTROL.can.return_value = False
        permissions.SETTINGS.can.return_value = False
        with pytest.raises(Exception) as error:
            plugin.on_api_command("discover", {})
        assert error.value.code == 403


def test_turn_off_is_explicit_even_with_stale_cache(plugin):
    with patch.object(plugin, "_client") as factory:
        factory.return_value.state.return_value = dict(state="off", attributes={})
        plugin._control("turn_off")
        factory.return_value.service.assert_called_once_with("light.printer", "turn_off")
    assert plugin.states["light.printer"]["isLightOn"] is False


def test_failed_command_does_not_invert_state(plugin):
    plugin.states["light.printer"] = dict(isLightOn=False)
    with patch.object(plugin, "_client") as factory:
        factory.return_value.service.side_effect = HomeAssistantError("Token rejected")
        factory.return_value.state.return_value = dict(state="off", attributes={})
        with pytest.raises(HomeAssistantError):
            plugin._control("toggle")
    assert plugin.states["light.printer"]["isLightOn"] is None
    assert plugin.states["light.printer"]["error"] == "Token rejected"


def test_external_change_updates_browser(plugin):
    with patch.object(plugin, "_client") as factory, patch.object(plugin, "_schedule_poll"):
        factory.return_value.entities.return_value = [
            dict(entity_id="light.printer", state="on", attributes={"friendly_name": "Printer"})
        ]
        plugin._poll(plugin._generation)
        assert plugin.states["light.printer"]["isLightOn"] is True
        plugin._plugin_manager.send_plugin_message.assert_called_once()
        plugin._poll(plugin._generation)
        assert plugin._plugin_manager.send_plugin_message.call_count == 1
        factory.return_value.entities.return_value = [
            dict(entity_id="light.printer", state="off", attributes={})
        ]
        plugin._poll(plugin._generation)
        assert plugin.states["light.printer"]["isLightOn"] is False
        assert plugin._plugin_manager.send_plugin_message.call_count == 2


def test_unavailable_is_not_off(plugin):
    with patch.object(plugin, "_client") as factory:
        factory.return_value.state.return_value = dict(state="unavailable", attributes={})
        assert plugin._refresh("light.printer")["isLightOn"] is None


def test_new_print_always_cancels_idle_timer(plugin):
    timer = Mock()
    plugin._idle_timers["light.printer"] = (timer, object())
    with patch.object(plugin._executor, "submit"):
        plugin.on_event(Events.PRINT_STARTED, {})
    timer.cancel.assert_called_once()
    assert not plugin._idle_timers


def test_stale_done_event_cannot_schedule_shutoff(plugin):
    plugin.config["turnOffPrintEnd"] = True
    with patch.object(plugin, "_control") as control:
        plugin._print_generation = 2
        plugin._handle_print_event(Events.PRINT_DONE, plugin._generation, 1)
        control.assert_not_called()


def test_old_timer_cannot_cancel_replacement(plugin):
    token = object()
    replacement = (Mock(), object())
    plugin._idle_timers["light.printer"] = replacement
    with patch.object(plugin, "_control") as control:
        plugin._idle_off("light.printer", plugin._generation, token)
        control.assert_not_called()
    assert plugin._idle_timers["light.printer"] == replacement


def test_idle_off_checks_printer(plugin):
    token = object()
    plugin._idle_timers["light.printer"] = (Mock(), token)
    plugin._printer.is_printing.return_value = True
    with patch.object(plugin, "_control") as control:
        plugin._idle_off("light.printer", plugin._generation, token)
        control.assert_not_called()


def test_zero_delay_and_explicit_start(plugin):
    plugin.config.update(turnOnPrintStart=True, turnOffPrintEnd=True)
    with patch.object(plugin, "_control") as control:
        plugin._handle_print_event(
            Events.PRINT_STARTED, plugin._generation, plugin._print_generation
        )
        plugin._handle_print_event(Events.PRINT_DONE, plugin._generation, plugin._print_generation)
        assert [c.args[0] for c in control.call_args_list] == ["turn_on", "turn_off"]


def test_shutdown_cancels_all_timers(plugin):
    timer = Mock()
    poll = Mock()
    plugin._idle_timers["light.printer"] = (timer, object())
    plugin._poll_timer = poll
    plugin.on_shutdown()
    timer.cancel.assert_called_once()
    poll.cancel.assert_called_once()
    assert not plugin._running


def test_light_defaults_are_applied_on_toggle(plugin):
    plugin.config.update(applyBrightness=True, brightness=80, applyColor=True, color="#ff0080")
    with patch.object(plugin, "_client") as factory:
        factory.return_value.state.return_value = dict(
            state="off", attributes={"supported_color_modes": ["rgb"]}
        )
        plugin._control("toggle")
        factory.return_value.service.assert_called_once_with(
            "light.printer", "turn_on", brightness_pct=80, rgb_color=[255, 0, 128]
        )


def test_manual_color_rejects_switch(plugin):
    plugin.config["entity_id"] = "switch.printer"
    with patch.object(plugin, "_client") as factory:
        factory.return_value.state.return_value = dict(state="on", attributes={})
        with pytest.raises(HomeAssistantError, match="does not support color"):
            plugin._control("turn_on", attributes={"color": "#ff0000"})
        factory.return_value.service.assert_not_called()


def test_status_error_uses_native_short_flash(plugin):
    plugin.config.update(statusColorsEnabled=True, alertFlash=True)
    with patch.object(plugin, "_client") as factory:
        factory.return_value.state.return_value = dict(
            state="on", attributes={"supported_color_modes": ["rgb"], "supported_features": 8}
        )
        plugin._handle_print_event(Events.ERROR, plugin._generation, plugin._print_generation)
        factory.return_value.service.assert_called_once_with(
            "light.printer", "turn_on", rgb_color=[255, 0, 0], flash="short"
        )


def test_failure_shutoff_wins_over_status_color(plugin):
    plugin.config.update(statusColorsEnabled=True, turnOffPrintFailure=True)
    with patch.object(plugin, "_control") as control:
        plugin._handle_print_event(
            Events.PRINT_FAILED, plugin._generation, plugin._print_generation
        )
        control.assert_called_once_with("turn_off", "light.printer", manual=False)


def test_additional_entities_are_independent(plugin):
    plugin.config["additionalEntities"] = [{"entity_id": "switch.room", "turnOnPrintStart": True}]
    with patch.object(plugin, "_control") as control:
        plugin._handle_print_event(
            Events.PRINT_STARTED, plugin._generation, plugin._print_generation
        )
        control.assert_called_once_with("turn_on", "switch.room", manual=False)


def test_extra_entity_delay_validation(plugin):
    plugin.config["additionalEntities"] = [{"entity_id": "switch.room", "turnOffPrintDelay": -1}]
    with pytest.raises(HomeAssistantError, match="delay"):
        plugin._validate_settings(plugin.config)


def test_gcode_is_opt_in_and_queued(plugin):
    with patch.object(plugin._executor, "submit") as submit:
        plugin.process_atcommand(None, "queuing", "OCTOLIGHT", "on")
        submit.assert_not_called()
        plugin.config["enableGcode"] = True
        plugin.process_atcommand(None, "queuing", "OCTOLIGHT", "off")
        submit.assert_called_once_with(
            plugin._queued_control, "turn_off", "light.printer", plugin._generation, {}
        )


@pytest.mark.parametrize(
    "parameters", ["", "on switch.unconfigured", "invalid", "on light.printer extra"]
)
def test_gcode_rejects_invalid_targets(plugin, parameters):
    plugin.config["enableGcode"] = True
    with patch.object(plugin._executor, "submit") as submit:
        plugin.process_atcommand(None, "queuing", "OCTOLIGHT", parameters)
        submit.assert_not_called()


def test_poll_uses_one_request_for_multiple_entities(plugin):
    plugin.config["additionalEntities"] = [{"entity_id": "switch.room"}]
    with patch.object(plugin, "_client") as factory, patch.object(plugin, "_schedule_poll"):
        factory.return_value.entities.return_value = [
            dict(entity_id="light.printer", state="off", attributes={}),
            dict(entity_id="switch.room", state="on", attributes={}),
        ]
        plugin._poll(plugin._generation)
        factory.return_value.entities.assert_called_once()
        factory.return_value.state.assert_not_called()
        assert plugin.states["switch.room"]["isLightOn"] is True


def test_unconfigured_entity_disappearing_is_reported(plugin):
    with patch.object(plugin, "_client") as factory, patch.object(plugin, "_schedule_poll"):
        factory.return_value.entities.return_value = []
        plugin._poll(plugin._generation)
    assert "not found" in plugin.states["light.printer"]["error"]


def test_event_dispatch_and_cached_reads_do_not_wait_for_network_lock(plugin, app):
    import threading

    held = threading.Event()
    release = threading.Event()

    def block_network():
        with plugin._lock:
            held.set()
            release.wait(5)

    worker = threading.Thread(target=block_network)
    worker.start()
    assert held.wait(2)
    try:
        with patch.object(plugin._executor, "submit") as submit:
            plugin.on_event(Events.PRINT_STARTED, {})
            submit.assert_called_once()
        with (
            app.test_request_context("/"),
            patch("octoprint_octolightHA.Permissions") as permissions,
        ):
            permissions.STATUS.can.return_value = True
            assert plugin.on_api_get(flask.request).status_code == 200
        assert not release.is_set()
    finally:
        release.set()
        worker.join(2)


@pytest.mark.parametrize(
    "existing,explicit,expected", [(False, False, False), (True, False, True), (True, True, False)]
)
def test_legacy_tls_migration(plugin, existing, explicit, expected):
    plugin._settings = Mock()
    plugin._settings.get.return_value = "http://ha.local" if existing else ""
    plugin._settings.has.return_value = explicit
    plugin.on_settings_migrate(1, None)
    assert plugin._settings.set_boolean.called is expected


def test_invalid_settings_are_reported_without_overwriting_config(plugin):
    plugin._settings = Mock()
    plugin.on_settings_save({"entity_id": "desk_lamp"})
    plugin._settings.set.assert_not_called()
    assert plugin.config["entity_id"] == "light.printer"
    message = plugin._plugin_manager.send_plugin_message.call_args.args[1]
    assert "complete entity" in message["settingsError"]


def test_minimal_extra_entity_is_normalized_for_ui(plugin):
    data = plugin._validated_settings({"additionalEntities": [{"entity_id": "switch.room"}]})
    assert data["additionalEntities"][0]["turnOnPrintStart"] is False
    assert data["additionalEntities"][0]["turnOffPrintDelay"] == 0


def test_string_booleans_are_rejected(plugin):
    with pytest.raises(HomeAssistantError, match="Checkbox"):
        plugin._validated_settings({"turnOnPrintStart": "false"})


def test_host_appearance_queues_capability_checked_control(plugin):
    plugin.config.update(enableGcode=True, additionalEntities=[{"entity_id": "light.room"}])
    with (
        patch.object(plugin._executor, "submit") as submit,
        patch.object(plugin, "_client") as client,
    ):
        plugin.process_atcommand(
            None, "queuing", "OCTOLIGHT", "set light.room brightness=75 color=#ff8000 flash=short"
        )
        submit.assert_called_once_with(
            plugin._queued_control,
            "turn_on",
            "light.room",
            plugin._generation,
            {"brightness": 75, "color": "#ff8000", "flash": "short"},
        )
        client.assert_not_called()


def test_host_commands_ignore_other_phases_and_names(plugin):
    plugin.config["enableGcode"] = True
    with patch.object(plugin._executor, "submit") as submit:
        plugin.process_atcommand(None, "sending", "OCTOLIGHT", "on")
        plugin.process_atcommand(None, "queuing", "OTHER", "on")
        submit.assert_not_called()


def test_queued_host_appearance_reaches_light_control(plugin):
    with patch.object(plugin, "_control") as control:
        plugin._queued_control(
            "turn_on", "light.printer", plugin._generation, {"brightness": 75, "color": "#ff8000"}
        )
        control.assert_called_once_with(
            "turn_on", "light.printer", {"brightness": 75, "color": "#ff8000"}
        )


def test_update_information_preserves_upstream_identity_and_source(plugin):
    plugin._plugin_version = "0.3.0"
    info = plugin.get_update_information()
    assert set(info) == {"octolightHA"}
    update = info["octolightHA"]
    assert update["user"] == "mark-bloom"
    assert update["repo"] == "OctoLight_Home-Assistant"
    assert update["pip"] == (
        "https://github.com/mark-bloom/OctoLight_Home-Assistant/archive/{target_version}.zip"
    )


def test_standalone_fork_command_is_not_claimed(plugin):
    plugin.config["enableGcode"] = True
    with patch.object(plugin._executor, "submit") as submit:
        plugin.process_atcommand(None, "queuing", "HALIGHT", "on")
        submit.assert_not_called()
