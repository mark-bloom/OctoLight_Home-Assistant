/* Exercise real Knockout bindings in Chromium using OctoPrint's bundled libraries. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {execFileSync} = require("node:child_process");
const {chromium} = require("playwright");
const python = process.env.PYTHON || "python";
const staticRoot = execFileSync(python, ["-c", "import octoprint,pathlib; print(pathlib.Path(octoprint.__file__).parent / 'static/js/lib')"], {encoding: "utf8"}).trim();
const defaults = JSON.parse(execFileSync(python, ["-c", "import json; from octoprint_octolightHA import OctoLightHAPlugin; p=OctoLightHAPlugin(); print(json.dumps(p.get_settings_defaults())); p.on_shutdown()"], {encoding: "utf8"}));
const pluginRoot = path.resolve("octoprint_octolightHA");
(async () => {
    const browser = await chromium.launch({headless: true});
    const page = await browser.newPage();
    page.setDefaultTimeout(5000);
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    try {
        await page.setContent('<div id="navbar_plugin_octolightHA">' + fs.readFileSync(path.join(pluginRoot, "templates/octolightHA_navbar.jinja2"), "utf8") + '</div><div id="settings_plugin_octolightHA">' + fs.readFileSync(path.join(pluginRoot, "templates/octolightHA_settings.jinja2"), "utf8") + '</div>');
        await page.addStyleTag({path: path.join(staticRoot, "../../css/bootstrap.css")});
        await page.addStyleTag({path: path.join(pluginRoot, "static/css/octolightHA.css")});
        const jqueryRoot = path.join(staticRoot, "jquery");
        const jqueryFile = fs.readdirSync(jqueryRoot).find(file => /^jquery(?:\.min)?\.js$/.test(file));
        await page.addScriptTag({path: path.join(jqueryRoot, jqueryFile)});
        await page.addScriptTag({path: path.join(staticRoot, "bootstrap/bootstrap.js")});
        await page.addScriptTag({path: path.join(staticRoot, "knockout.js")});
        await page.addScriptTag({path: path.join(staticRoot, "knockout.mapping-latest.js")});
        await page.evaluate(defaults => {
            window.OCTOPRINT_VIEWMODELS = [];
            window.notifications = [];
            window.PNotify = function (options) { notifications.push(options); };
            window.calls = [];
            window.allowControl = ko.observable(true);
            window.isUser = ko.observable(true);
            window.snapshot = {entities: [{entity_id: "light.printer", name: "Printer", icon: "lightbulb", isLightOn: false, available: true, error: null, attributes: {brightness: 128}, capabilities: {brightness: true, color: true}}]};
            window.OctoPrint = {
                simpleApiGet: function () { calls.push({method: "GET"}); return $.Deferred().resolve(snapshot).promise(); },
                simpleApiCommand: function (plugin, command, data) {
                    calls.push({method: "POST", plugin: plugin, command: command, data: data});
                    if (command === "discover") return $.Deferred().resolve({entities: [{entity_id: "switch.desk_lamp", name: "Desk lamp", state: "off"}]}).promise();
                    if (command === "test") return $.Deferred().resolve({state: "off"}).promise();
                    return $.Deferred().resolve(snapshot).promise();
                }
            };
            window.settingsVM = {settings: ko.mapping.fromJS({plugins: {octolightHA: defaults}})};
        }, defaults);
        await page.addScriptTag({path: path.join(pluginRoot, "static/js/octolightHA.js")});
        await page.waitForFunction(() => OCTOPRINT_VIEWMODELS.length === 1);
        await page.evaluate(() => {
            window.vm = new OCTOPRINT_VIEWMODELS[0].construct([settingsVM,
                {isUser: isUser, hasPermission: () => allowControl()}, {permissions: {CONTROL: "CONTROL"}}]);
            vm.onBeforeBinding();
            ko.applyBindings(vm, document.getElementById("navbar_plugin_octolightHA"));
            ko.applyBindings(vm, document.getElementById("settings_plugin_octolightHA"));
            vm.onStartupComplete();
        });
        assert.equal(await page.locator(".octolight-indicator").count(), 1);
        assert.equal(await page.locator("input[type=range]").count(), 2);
        await page.getByRole("button", {name: "Light controls", exact: true}).click();
        assert.equal(await page.locator(".octolight-live input[type=range]").isVisible(), true);
        await page.locator(".octolight-live input[type=range]").fill("60");
        await page.locator(".octolight-live input[type=range]").dispatchEvent("change");
        assert.equal(await page.evaluate(() => calls.at(-1).data.brightness), 60);
        assert.equal(await page.locator(".octolight-live input[type=range]").isVisible(), true);
        await page.evaluate(() => { window.originalRow = vm.entities()[0]; snapshot.entities[0].attributes = {brightness: 204}; document.activeElement.blur(); vm.apply(snapshot); });
        assert.equal(await page.evaluate(() => vm.entities()[0] === originalRow), true);
        assert.equal(await page.evaluate(() => vm.entities()[0].brightnessValue()), 80);
        await page.locator(".octolight-indicator").click();
        assert.equal(await page.evaluate(() => calls.at(-1).command), "toggle");
        assert.equal(await page.evaluate(() => calls.at(-1).plugin), "octolightHA");
        await page.evaluate(() => allowControl(false));
        await page.locator(".octolight-indicator").dispatchEvent("click");
        assert.equal(await page.evaluate(() => calls.filter(c => c.command === "toggle").length), 1);
        await page.evaluate(() => allowControl(true));
        await page.getByRole("button", {name: "Search Home Assistant", exact: true}).click();
        assert.equal(await page.evaluate(() => settingsVM.settings.plugins.octolightHA.entity_id()), "switch.desk_lamp");
        await page.getByRole("button", {name: "Add entity", exact: true}).click();
        assert.equal(await page.getByPlaceholder("light.room").count(), 1);
        await page.getByRole("button", {name: "Remove", exact: true}).click();
        await page.locator("#settings_plugin_octolightHA input[type=range]").fill("75");
        await page.locator("#settings_plugin_octolightHA input[type=range]").dispatchEvent("change");
        assert.equal(await page.evaluate(() => calls.at(-1).data.brightness), 75);
        await page.evaluate(() => vm.onDataUpdaterPluginMessage("octolightHA", {entities: [{entity_id: "switch.desk_lamp", name: "Lamp", icon: "power-off", isLightOn: true, available: true, error: null, attributes: {}, capabilities: {}}]}));
        assert.equal(await page.locator("input[type=range]").count(), 0);
        assert.equal(await page.locator(".octolight-indicator.off").count(), 0);
        await page.evaluate(() => vm.onDataUpdaterPluginMessage("octolightHA", {entities: [{entity_id: "switch.desk_lamp", icon: "power-off", name: "Lamp", isLightOn: null, available: false, error: "Entity not found", attributes: {}, capabilities: {}}]}));
        assert.match(await page.locator(".octolight-indicator").getAttribute("title"), /Entity not found/);
        await page.evaluate(() => vm.onDataUpdaterPluginMessage("octolightHA", {settingsError: "Use a complete entity ID"}));
        assert.equal(await page.evaluate(() => notifications.at(-1).text), "Use a complete entity ID");
        await page.evaluate(() => { isUser(false); vm.onUserLoggedOut(); });
        assert.equal(await page.locator(".octolight-indicator").count(), 0);
        assert.deepEqual(errors, []);
        console.log("Chromium: bindings, discovery/autofill, controls, permissions, external state, errors and logout passed");
    } finally {
        await browser.close();
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
