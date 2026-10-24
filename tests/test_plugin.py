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
    p.config = dict(p.get_settings_defaults(), address='http://ha.local', api_key='secret', entity_id='light.printer')
    p._identifier = 'octolightHA'
    p._logger = logging.getLogger('test')
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
    with app.test_request_context('/'), patch('octoprint_octolightHA.Permissions') as permissions:
        permissions.STATUS.can.return_value = True
        with patch.object(plugin, '_client') as client:
            assert plugin.on_api_get(flask.request).json['state'] is None
            client.assert_not_called()
    with app.test_request_context('/?action=toggle'), patch('octoprint_octolightHA.Permissions') as permissions:
        permissions.STATUS.can.return_value = True
        assert plugin.on_api_get(flask.request)[1] == 405


def test_commands_require_control(plugin, app):
    with app.test_request_context('/'), patch('octoprint_octolightHA.Permissions') as permissions:
        permissions.CONTROL.can.return_value = False
        permissions.SETTINGS.can.return_value = False
        with pytest.raises(Exception) as error:
            plugin.on_api_command('turnOff', {})
        assert error.value.code == 403


def test_discovery_requires_settings(plugin, app):
    with app.test_request_context('/'), patch('octoprint_octolightHA.Permissions') as permissions:
        permissions.CONTROL.can.return_value = False
        permissions.SETTINGS.can.return_value = False
        with pytest.raises(Exception) as error:
            plugin.on_api_command('discover', {})
        assert error.value.code == 403


def test_turn_off_is_explicit_even_with_stale_cache(plugin):
    with patch.object(plugin, '_client') as factory:
        factory.return_value.state.return_value = dict(state='off', attributes={})
        plugin._control('turn_off')
        factory.return_value.service.assert_called_once_with('light.printer', 'turn_off')
    assert plugin.states['light.printer']['isLightOn'] is False


def test_failed_command_does_not_invert_state(plugin):
    plugin.states['light.printer'] = dict(isLightOn=False)
    with patch.object(plugin, '_client') as factory:
        factory.return_value.service.side_effect = HomeAssistantError('Token rejected')
        with pytest.raises(HomeAssistantError):
            plugin._control('toggle')
    assert plugin.states['light.printer']['isLightOn'] is None
    assert plugin.states['light.printer']['error'] == 'Token rejected'


def test_external_change_updates_browser(plugin):
    with patch.object(plugin, '_client') as factory, patch.object(plugin, '_schedule_poll'):
        factory.return_value.state.return_value = dict(state='on', attributes={'friendly_name': 'Printer'})
        plugin._poll(plugin._generation)
        assert plugin.states['light.printer']['isLightOn'] is True
        plugin._plugin_manager.send_plugin_message.assert_called_once()
        plugin._poll(plugin._generation)
        assert plugin._plugin_manager.send_plugin_message.call_count == 1
        factory.return_value.state.return_value = dict(state='off', attributes={})
        plugin._poll(plugin._generation)
        assert plugin.states['light.printer']['isLightOn'] is False
        assert plugin._plugin_manager.send_plugin_message.call_count == 2


def test_unavailable_is_not_off(plugin):
    with patch.object(plugin, '_client') as factory:
        factory.return_value.state.return_value = dict(state='unavailable', attributes={})
        assert plugin._refresh('light.printer')['isLightOn'] is None


def test_new_print_always_cancels_idle_timer(plugin):
    timer = Mock()
    plugin._idle_timers['light.printer'] = (timer, object())
    with patch.object(plugin._executor, 'submit'):
        plugin.on_event(Events.PRINT_STARTED, {})
    timer.cancel.assert_called_once()
    assert not plugin._idle_timers


def test_stale_done_event_cannot_schedule_shutoff(plugin):
    plugin.config['turnOffPrintEnd'] = True
    with patch.object(plugin, '_control') as control:
        plugin._print_generation = 2
        plugin._handle_print_event(Events.PRINT_DONE, plugin._generation, 1)
        control.assert_not_called()


def test_old_timer_cannot_cancel_replacement(plugin):
    token = object()
    replacement = (Mock(), object())
    plugin._idle_timers['light.printer'] = replacement
    with patch.object(plugin, '_control') as control:
        plugin._idle_off('light.printer', plugin._generation, token)
        control.assert_not_called()
    assert plugin._idle_timers['light.printer'] == replacement


def test_idle_off_checks_printer(plugin):
    token = object()
    plugin._idle_timers['light.printer'] = (Mock(), token)
    plugin._printer.is_printing.return_value = True
    with patch.object(plugin, '_control') as control:
        plugin._idle_off('light.printer', plugin._generation, token)
        control.assert_not_called()


def test_zero_delay_and_explicit_start(plugin):
    plugin.config.update(turnOnPrintStart=True, turnOffPrintEnd=True)
    with patch.object(plugin, '_control') as control:
        plugin._handle_print_event(Events.PRINT_STARTED, plugin._generation, plugin._print_generation)
        plugin._handle_print_event(Events.PRINT_DONE, plugin._generation, plugin._print_generation)
        assert [c.args[0] for c in control.call_args_list] == ['turn_on', 'turn_off']


def test_shutdown_cancels_all_timers(plugin):
    timer = Mock()
    poll = Mock()
    plugin._idle_timers['light.printer'] = (timer, object())
    plugin._poll_timer = poll
    plugin.on_shutdown()
    timer.cancel.assert_called_once()
    poll.cancel.assert_called_once()
    assert not plugin._running
