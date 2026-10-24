$(function () {
    "use strict";
    function OctolightHAViewModel(parameters) {
        var self = this;
        self.settingsViewModel = parameters[0];
        self.loginState = parameters[1];
        self.access = parameters[2];
        self.entities = ko.observableArray([]);
        self.discovered = ko.observableArray([]);
        self.search = ko.observable("");
        self.selectedEntity = ko.observable();
        self.message = ko.observable("");
        self.busy = ko.observable(false);
        self.rows = {};
        self.canControl = ko.pureComputed(function () {
            return self.loginState.hasPermission(self.access.permissions.CONTROL);
        });
        self.filteredEntities = ko.pureComputed(function () {
            var query = self.search().toLowerCase();
            return self.discovered().filter(function (entity) {
                return (entity.entity_id + " " + entity.name).toLowerCase().indexOf(query) !== -1;
            });
        });
        self.selectedEntity.subscribe(function (entity) {
            if (entity && self.settings) self.settings.plugins.octolightHA.entity_id(entity.entity_id);
        });
        self.onBeforeBinding = function () {
            self.settings = self.settingsViewModel.settings;
        };
        self.apply = function (data) {
            if (!data || !data.entities) return;
            self.entities(data.entities.map(function (entity) {
                var previous = self.rows[entity.entity_id];
                var attrs = entity.attributes || {};
                entity.brightnessValue = previous ? previous.brightnessValue : ko.observable(Math.round((attrs.brightness || 255) / 255 * 100));
                var channels = attrs.rgb_color || [255, 255, 255];
                var hex = "#" + channels.map(function (n) { return ("0" + n.toString(16)).slice(-2); }).join("");
                entity.colorValue = previous ? previous.colorValue : ko.observable(hex);
                self.rows[entity.entity_id] = entity;
                return entity;
            }));
        };
        self.failure = function (xhr) {
            var error = xhr.responseJSON && xhr.responseJSON.error;
            self.message(error || "Could not contact OctoLight. Check your connection and permissions.");
            new PNotify({title: "OctoLight Home Assistant", text: self.message(), type: "error"});
        };
        self.command = function (command, data) {
            self.busy(true);
            self.message("");
            return OctoPrint.simpleApiCommand("octolightHA", command, data || {})
                .done(function (result) {
                    if (command !== "discover" && command !== "test") self.apply(result);
                }).fail(self.failure).always(function () { self.busy(false); });
        };
        self.toggle = function (entity) {
            if (!self.canControl() || self.busy()) return;
            self.command("toggle", {entity_id: entity.entity_id});
        };
        self.setBrightness = function (entity) {
            if (self.canControl() && !self.busy()) self.command("setLight", {entity_id: entity.entity_id, brightness: Number(entity.brightnessValue())});
        };
        self.setColor = function (entity) {
            if (self.canControl() && !self.busy()) self.command("setLight", {entity_id: entity.entity_id, color: entity.colorValue()});
        };
        self.connection = function () {
            var config = self.settings.plugins.octolightHA;
            return {address: config.address(), api_key: config.api_key(),
                verify_certificate: config.verify_certificate(), entity_id: config.entity_id()};
        };
        self.discover = function () {
            self.command("discover", self.connection()).done(function (data) {
                self.discovered(data.entities || []);
                // Only auto-fill when unambiguous; never guess between similarly named devices.
                if (!self.settings.plugins.octolightHA.entity_id() && data.entities.length === 1) {
                    self.settings.plugins.octolightHA.entity_id(data.entities[0].entity_id);
                }
                self.message("Found " + data.entities.length + " controllable entities. Search by name or ID.");
                self.refresh();
            });
        };
        self.test = function () {
            self.command("test", self.connection()).done(function (data) {
                self.message("Connection successful. Entity state: " + data.state);
            });
        };
        self.addEntity = function () {
            self.settings.plugins.octolightHA.additionalEntities.push({entity_id: ko.observable(""),
                icon: ko.observable("lightbulb"), turnOnPrintStart: ko.observable(false),
                turnOffPrintEnd: ko.observable(false), turnOffPrintDelay: ko.observable(0),
                turnOffPrintFailure: ko.observable(false), turnOffPrintCancellation: ko.observable(false)});
        };
        self.removeEntity = function (entity) {
            self.settings.plugins.octolightHA.additionalEntities.remove(entity);
        };
        self.refresh = function () {
            if (self.loginState.isUser()) OctoPrint.simpleApiGet("octolightHA").done(self.apply);
        };
        self.onStartupComplete = self.refresh;
        self.onUserLoggedIn = self.refresh;
        self.onUserLoggedOut = function () { self.entities([]); };
        self.onDataUpdaterReconnect = self.refresh;
        self.onDataUpdaterPluginMessage = function (plugin, data) {
            if (plugin === "octolightHA" && self.loginState.isUser()) self.apply(data);
        };
    }
    OCTOPRINT_VIEWMODELS.push({construct: OctolightHAViewModel,
        dependencies: ["settingsViewModel", "loginStateViewModel", "accessViewModel"],
        elements: ["#navbar_plugin_octolightHA", "#settings_plugin_octolightHA"]});
});
