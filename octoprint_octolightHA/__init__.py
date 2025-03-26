# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import octoprint.plugin
from octoprint.events import Events
import flask
import traceback

# HomeAssistant Compatibility
import requests

class OctoLightHAPlugin(
        octoprint.plugin.AssetPlugin,
        octoprint.plugin.StartupPlugin,
        octoprint.plugin.TemplatePlugin,
        octoprint.plugin.SimpleApiPlugin,
        octoprint.plugin.SettingsPlugin,
        octoprint.plugin.EventHandlerPlugin,
        octoprint.plugin.RestartNeedingPlugin
    ):

    light_state = False

    def __init__(self):
        self.config = dict()
        self.isLightOn = False

    ### REMOVE SETTINGS IF UPLOADED ###
    def get_settings_defaults(self):
        return dict(
            address = '',
            api_key = '',
            entity_id = '',
            verify_certificate = False,
            turnOnPrintStart = False,
            turnOffPrintEnd = False,
            turnOffPrintFailure = False,
            turnOffPrintCancellation = False
        )
    
    def on_settings_initialized(self):
        self.reload_settings()

    def reload_settings(self):
        for k, v in self.get_settings_defaults().items():
            if type(v) == str:
                v = self._settings.get([k])
            elif type(v) == int:
                v = self._settings.get_int([k])
            elif type(v) == float:
                v = self._settings.get_float([k])
            elif type(v) == bool:
                v = self._settings.get_boolean([k])

            self.config[k] = v
            self._logger.debug("{}: {}".format(k, v))

    def get_template_configs(self):
        return [
            dict(type="navbar", custom_bindings=True),
            dict(type="settings", custom_bindings=True)
        ]

    def get_assets(self):
        # Define your plugin's asset files to automatically include in the
        # core UI here.
        return dict(
            js=["js/octolightHA.js"],
            css=["css/octolightHA.css"],
            #less=["less/octolightHA.less"]
        )
    
    def get_HA_state(self):
        # Agnostic to entity type
        self._logger.debug("Running get_HA_state")
        _entity_id = self.config['entity_id']
        url = self.config['address'] + '/api/states/' + _entity_id
        self._logger.debug("get_HA_state url is: {}".format(url))
        
        headers = dict(Authorization='Bearer ' + self.config['api_key'])

        response = None
        status = None

        verify_certificate = self.config['verify_certificate']
        try:
            response = requests.get(url, headers=headers, verify=verify_certificate)
            self._logger.debug("get_HA_state response is: {}".format(response))
        except (
                requests.exceptions.InvalidURL,
                requests.exceptions.ConnectionError
        ):
            self._logger.error("Unable to communicate with server. Check settings.")
        except Exception:
            self._logger.exception("Exception while making API call")

        try:
            status = response.json()['state']
            self._logger.debug("Status response formatted as: {}".format(status))
        except Exception as e:
            status = 'off'
            self._logger.error("Status response invalid format: {}".format(status))
            
        if(status == 'on'):
            light_bool = True
        else:
            light_bool = False

        self._logger.debug("STATUS: Current light status is: {}".format(self.light_state))
        return light_bool
    
    def toggle_HA_state(self):
        ## AGNOSTIC
        self._logger.debug("Running toggle_HA_state")
        _entity_id = self.config['entity_id']
        _entity_type = _entity_id.split('.')[0]
        self._logger.debug("Entity: ",_entity_id)

        url = self.config['address'] + '/api/services/'+ _entity_type +'/toggle'
        data = '{"entity_id":"' + _entity_id + '"}'
        headers = dict(Authorization='Bearer ' + self.config['api_key'])
        verify_certificate = self.config['verify_certificate']
        response = None
        
        # Check current status
        light_bool = self.get_HA_state()
        
        try:
            response = requests.post(url, headers=headers, data=data, verify=verify_certificate)
        except (
                requests.exceptions.InvalidURL,
                requests.exceptions.ConnectionError
        ):
            self._logger.error("Unable to communicate with server. Check settings.")
        except Exception as e:
            self._logger.error(traceback.format_exc())
        
        # Invert, get_HA_state takes an undetermined amount of time
        light_bool = not light_bool
        
        self._logger.debug("TOGGLE: Current light status is (expected): {}".format(light_bool))
        return light_bool
        
    def on_after_startup(self):
        self._logger.info("--------------------------------------------")
        self._logger.info("OctoLightHA started, listening for GET request")
        self._logger.info("Address: {}, API_Key: {}, Entity_ID: {}, Verify_Certificate: {}".format(
            self._settings.get(["address"]),
            self._settings.get(["api_key"]),
            self._settings.get(["entity_id"]),
            self._settings.get(["verify_certificate"]),
        ))

        self.light_state = self.get_HA_state()
        self.isLightOn = self.light_state
        self._plugin_manager.send_plugin_message(self._identifier, dict(isLightOn=self.light_state))
        self._logger.debug("POST request. Light state: {}, isLightOn: {}".format(
            self.light_state,
            self.isLightOn
        ))
        
        self._logger.debug("Current light status is: {}".format(self.light_state))
        self._logger.debug("--------------------------------------------")

        self._plugin_manager.send_plugin_message(self._identifier, dict(isLightOn=self.light_state))

    def light_toggle(self):
        self._logger.debug("PRE request. Light state: {}, isLightOn: {}".format(
            self.light_state,
            self.isLightOn
        ))		
        self.light_state = self.toggle_HA_state() # Returns the current state of the light
        self.isLightOn = self.light_state
        self._plugin_manager.send_plugin_message(self._identifier, dict(isLightOn=self.light_state))
        self._logger.debug("POST request. Light state: {}, isLightOn: {}".format(
            self.light_state,
            self.isLightOn
        ))
        return self.light_state

    def on_api_get(self, request):
        old_isLightOn = self.isLightOn
        self._logger.debug("API REQUEST isLightOn: {}".format(self.isLightOn))
        action = request.args.get('action', default="toggle", type=str)

        if action == "toggle":
            self._logger.debug("Running api action toggle")
            self.light_toggle()

            if (old_isLightOn != self.isLightOn):
                self._logger.debug("TOGGLE: Light state changed.")

            return flask.jsonify(state=self.light_state)

        elif action == "getState":
            # Unused
            self._logger.debug("Running api action getstate")
            self.light_state = self.get_HA_state()
            self.isLightOn = self.light_state

            if (old_isLightOn != self.isLightOn):
                self._logger.debug("GETSTATE: Light state changed.")

            return flask.jsonify(state=self.light_state)

        elif action == "turnOn":
            # Unused
            self._logger.debug("Running api action turnon")
            if not self.light_state:
                self.light_state = self.light_toggle()
            if (old_isLightOn != self.isLightOn):
                self._logger.debug("TURNON: Light state changed.")

            return flask.jsonify(state=self.light_state)

        elif action == "turnOff":
            # Unused
            self._logger.debug("Running api action turnoff")
            if self.light_state:
                self.light_state = self.light_toggle()
            if (old_isLightOn != self.isLightOn):
                self._logger.debug("TURNOFF: Light state changed.")

            return flask.jsonify(state=self.light_state)

        else:
            return flask.jsonify(error="action not recognized")

    def on_event(self, event, payload):
        if event == Events.CLIENT_OPENED:
            self._plugin_manager.send_plugin_message(self._identifier, dict(isLightOn=self.light_state))
            return
        elif event == Events.PRINT_STARTED and self.config['turnOnPrintStart']:
            if not self.light_state:
                self.light_state = self.light_toggle()
                self._logger.debug("PRINT_STARTED: Light state changed.")
            return
        elif (event == Events.PRINT_DONE and self.config['turnOffPrintEnd']) or (event == Events.PRINT_FAILED and self.config['turnOffPrintFailure']) or (event == Events.PRINT_CANCELLED and self.config['turnOffPrintCancellation']):
            if self.light_state:
                self.light_state = self.light_toggle()
                self._logger.debug("PRINT_DONE: Light state changed.")
            return
        

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self.reload_settings()

    def get_update_information(self):
        return dict(
            octolightHA=dict(
                displayName="OctoLightHA",
                displayVersion=self._plugin_version,

                type="github_release",
                current=self._plugin_version,

                user="mark.bloom",
                repo="OctoLightHA",
                pip="https://github.com/mark-bloom/OctoLight_Home-Assistant/archive/{target}.zip"
            )
        )

    def register_custom_events(self):
        return ["light_state_changed"]

__plugin_pythoncompat__ = ">=2.7,<4"
__plugin_implementation__ = OctoLightHAPlugin()

__plugin_hooks__ = {
    "octoprint.plugin.softwareupdate.check_config":
    __plugin_implementation__.get_update_information
}
