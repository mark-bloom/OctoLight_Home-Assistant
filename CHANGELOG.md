# Changelog

## 0.3.0

OctoLight Home Assistant gains searchable
Home Assistant entities, brightness and colour controls, and optional lighting
that follows your print's progress. Existing installations upgrade in place.

### Lights that are easier to set up and control

- Search Home Assistant by friendly name or entity ID instead of copying IDs by
  hand. A single supported entity is selected automatically when the field is empty.
- Test your connection and selected entity before saving settings, without changing
  the light's state. Connection errors now explain problems such as rejected tokens,
  missing entities, certificate failures and unreachable servers.
- Control brightness and RGB colour from each light's navbar menu, where the light
  supports them. Optional defaults apply your preferred appearance when turning on.
- Configure additional lights and switches independently, with their own navbar
  icons, print automation and delayed shutoff settings.
- Keep OctoPrint in sync with changes made in Home Assistant or other apps. State is
  refreshed every 10 seconds by default; unavailable lights are shown as unavailable.

### Lighting that follows your print

- Enable optional, customisable status colours: white for printing, amber for pause,
  green for completion, red for errors and orange for cancellation.
- Request a native short flash on errors when supported by the light. This uses
  Home Assistant's flash capability; it does not repeatedly blink the light in software.
- Shutoff timers are cancelled by new prints, manual controls, settings changes and
  shutdown. Old callbacks cannot turn lights off during a later running or paused print.
- Keep OctoPrint responsive while Home Assistant is slow or unavailable: network
  requests have timeouts and run outside event and serial command dispatch threads.

### G-code and integrations

Enable **@OCTOLIGHT host commands** in settings to control configured lights from
OctoPrint G-code scripts, streamed print files, the Terminal or OctoDash actions:

```gcode
@OCTOLIGHT on
@OCTOLIGHT set brightness=75 color=#ff8000
@OCTOLIGHT set light.printer color=#ff0000 flash=short
@OCTOLIGHT off
```

Commands support on, off, toggle and appearance changes. They run asynchronously;
printing directly from the printer's SD card does not process these host commands.
Brightness, RGB colour and flashes require the relevant light capabilities.

### Upgrade notes

- The plugin identifier (`octolightHA`), Python package (`octoprint_octolightHA`),
  distribution (`OctoLight-Home-Assistant`) and settings namespace remain compatible
  with existing installations. The address, token, entity and print settings are
  retained automatically. There is no import step.
- Automatic updates continue to use the original
  `mark-bloom/OctoLight_Home-Assistant` repository.
- **API change:** light controls now require authenticated, permission-checked JSON
  **POST** requests to `/api/plugin/octolightHA`; GET only reads state. Integrations
  using GET to toggle, turn on or turn off must migrate. For example, send
  `{"command": "turnOn"}` to turn on the primary entity.
- New configurations verify HTTPS certificates by default; existing explicit and
  implicit preferences are preserved during upgrade.
- Tokens are no longer logged and are restricted to users with Settings permission.
  Light controls require Control permission, and state access requires Status permission.
- If you installed the separately published Home Assistant Light Control fork,
  disable it before using both plugins for the same lights. Its separate settings
  are not imported automatically, and its `@HALIGHT` commands must be changed to
  `@OCTOLIGHT` for this plugin.

### Compatibility and validation

- Requires Python `>=3.9,<4`. Supports Home Assistant `light`, `switch` and
  `input_boolean` entities; switches and input booleans provide on/off control.
- Tested with OctoPrint **1.11.8** on Python **3.9 and 3.10**, and OctoPrint
  **2.0.0rc7** on Python **3.12**. OctoPrint 2 validation covers this release
  candidate; later versions require verification.
- Automated checks cover backend behaviour, installed-plugin loading and API access
  in a local OctoPrint server, browser controls in Chromium, and package contents.
- Validation uses Linux and a simulated Home Assistant. Physical printers, real Home
  Assistant devices, Windows and macOS have not been verified. Colour reproduction
  and native flash behaviour depend on the device and its Home Assistant integration.

Packages are built with isolated Python tooling. GitHub release drafts include an
installable wheel, a source archive and SHA256 checksums. CI checks the supported
OctoPrint/Python combinations, with dependency updates and workflow validation.
