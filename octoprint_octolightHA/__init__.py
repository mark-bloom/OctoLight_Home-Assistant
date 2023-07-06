# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import octoprint.plugin
from octoprint.events import Events
import flask

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
		_entity_id = self.config['entity_id']
		url = self.config['address'] + '/api' + _entity_id
		
		headers = dict(Authorization='Bearer ' + self.config['api_key'])

		response = None
		verify_certificate = self.config['verify_certificate']
		try:
			response = requests.get(url, headers=headers, verify=verify_certificate)
		except (
				requests.exceptions.InvalidURL,
				requests.exceptions.ConnectionError
        ):
			self._logger.error("Unable to communicate with server. Check settings.")
		except Exception:
			self._logger.exception("Exception while making API call")

		status = response.json()['state']
		if(status == 'on'):
			light_bool = True
		else:
			light_bool = False

		self._logger.debug("STATUS: Current light status is: {}".format(self.light_state))
		return light_bool
	
	def toggle_HA_state(self):
		self._logger.debug("Running toggle_HA_state")
		_entity_id = self.config['entity_id']
		url = self.config['address'] + '/api/services/light/toggle'
		data = '{"entity_id":"' + _entity_id + '"}'
		
		headers = dict(Authorization='Bearer ' + self.config['api_key'])

		response = None
		verify_certificate = self.config['verify_certificate']
		try:
			response = requests.post(url, headers=headers, data=data, verify=verify_certificate)
		except (
				requests.exceptions.InvalidURL,
				requests.exceptions.ConnectionError
        ):
			self._logger.error("Unable to communicate with server. Check settings.")
		except Exception:
			self._logger.exception("Exception while making API call")
		
		status = response.json()[0]['state']
		if status == 'on':
			light_bool = True
		else:
			light_bool = False
		
		self._logger.debug("TOGGLE: Current light status is: {}".format(self.light_state))
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
			self._logger.debug("Running api action getstate")
			self.light_state = self.get_HA_state()
			self.isLightOn = self.light_state

			if (old_isLightOn != self.isLightOn):
				self._logger.debug("GETSTATE: Light state changed.")

			return flask.jsonify(state=self.light_state)

		elif action == "turnOn":
			self._logger.debug("Running api action turnon")
			if not self.light_state:
				self.light_state = self.light_toggle()
			if (old_isLightOn != self.isLightOn):
				self._logger.debug("TURNON: Light state changed.")

			return flask.jsonify(state=self.light_state)

		elif action == "turnOff":
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

	def on_settings_save(self, data):
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
		self.reload_settings()

	def get_update_information(self):
		return False

	def register_custom_events(self):
		return ["light_state_changed"]

__plugin_pythoncompat__ = ">=2.7,<4"
__plugin_implementation__ = OctoLightHAPlugin()

__plugin_hooks__ = {
	"octoprint.plugin.softwareupdate.check_config":
	__plugin_implementation__.get_update_information
}
