"""Opt-in integration check against a real, disposable OctoPrint server."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
import yaml

pytestmark = pytest.mark.skipif(
    os.environ.get("OCTOLIGHT_SERVER_TEST") != "1",
    reason="set OCTOLIGHT_SERVER_TEST=1 for live server check",
)


def wait_for(check, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except requests.RequestException:
            pass
        time.sleep(0.2)
    pytest.fail("Timed out waiting for local test server")


@pytest.mark.parametrize("installation", ["fresh", "implicit-tls", "verified", "unverified"])
def test_real_octoprint_api(tmp_path, installation):
    class HA(BaseHTTPRequestHandler):
        state = "off"
        calls = []

        def log_message(self, *args):
            pass

        def reply(self, payload, code=200):
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            assert self.headers.get("Authorization") == "Bearer local-ha-test-token"
            state = dict(
                entity_id="light.printer",
                state=HA.state,
                attributes={
                    "friendly_name": "Printer",
                    "supported_color_modes": ["rgb"],
                    "supported_features": 8,
                },
            )
            if self.path == "/api/states":
                self.reply([state])
            elif self.path == "/api/states/light.printer":
                self.reply(state)
            else:
                self.reply({"message": "Entity not found"}, 404)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            HA.calls.append((self.path, data))
            HA.state = "on" if self.path.endswith("turn_on") else "off"
            self.reply([])

    ha = ThreadingHTTPServer(("127.0.0.1", 0), HA)
    worker = threading.Thread(target=ha.serve_forever, daemon=True)
    worker.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # These fields use the original plugin's namespace and pre-upgrade schema.
    # No import API or second plugin identity should be necessary after upgrading.
    legacy = dict(
        address="http://127.0.0.1:" + str(ha.server_port) + "/",
        api_key="local-ha-test-token",
        entity_id="light.printer",
        turnOnPrintStart=False,
        turnOffPrintEnd=True,
        turnOffPrintDelay=12,
        turnOffPrintFailure=True,
        turnOffPrintCancellation=True,
        unknown_legacy_marker="preserve",
    )
    if installation in ("verified", "unverified"):
        legacy["verify_certificate"] = installation == "verified"
    # OctoPrint removes stored values equal to the current defaults when saving.
    storage_defaults = {"turnOnPrintStart": False, "verify_certificate": True}
    config = {
        "server": {
            "firstRun": False,
            "onlineCheck": {"enabled": False},
            "pluginBlacklist": {"enabled": False},
        },
        "plugins": {
            "_disabled": [
                "discovery",
                "tracking",
                "announcements",
                "softwareupdate",
                "errortracking",
                "achievements",
                "pluginmanager",
                "health_check",
                "healthcheck",
                "ha_light_control",
            ]
        },
    }
    if installation != "fresh":
        config["plugins"]["octolightHA"] = legacy
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config))
    command = [sys.executable, "-m", "octoprint", "-b", str(tmp_path)]
    for name, group in (("admin", "admins"), ("reader", "readonly")):
        subprocess.run(
            command + ["user", "add", name, "--password", "local-test-only", "--group", group],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
    output = (tmp_path / "server-output.log").open("w")
    server = subprocess.Popen(
        command + ["serve", "--host", "127.0.0.1", "--port", str(port)],
        cwd=tmp_path,
        stdout=output,
        stderr=subprocess.STDOUT,
    )
    base = "http://127.0.0.1:" + str(port)
    try:
        wait_for(lambda: requests.get(base + "/api/version", timeout=1).status_code in (200, 403))
        assert requests.get(base + "/api/plugin/octolightHA", timeout=5).status_code == 403

        def login(name):
            session = requests.Session()
            assert session.get(base + "/", timeout=10).status_code == 200
            for key, value in session.cookies.items():
                if key.startswith("csrf_token"):
                    session.headers["X-CSRF-Token"] = value
            assert (
                session.post(
                    base + "/api/login", json={"user": name, "pass": "local-test-only"}, timeout=5
                ).status_code
                == 200
            )
            return session

        admin = login("admin")
        reader = login("reader")
        api = base + "/api/plugin/octolightHA"
        asset = admin.get(base + "/plugin/octolightHA/static/js/octolightHA.js", timeout=5)
        assert asset.status_code == 200
        assert 'simpleApiCommand("octolightHA"' in asset.text
        settings = admin.get(base + "/api/settings", timeout=5).json()["plugins"]["octolightHA"]
        assert settings["verify_certificate"] is (installation in ("fresh", "verified"))
        if installation != "fresh":
            wait_for(lambda: admin.get(api, timeout=5).json()["state"] is False)
            for key, value in legacy.items():
                assert settings[key] == value
            persisted = yaml.safe_load((tmp_path / "config.yaml").read_text())["plugins"]
            for key, value in legacy.items():
                assert persisted["octolightHA"].get(key, storage_defaults.get(key)) == value
            assert "ha_light_control" not in persisted
        assert reader.post(api, json={"command": "turnOn"}, timeout=5).status_code == 403
        assert reader.post(api, json={"command": "discover"}, timeout=5).status_code == 403
        connection = dict(
            address="http://127.0.0.1:" + str(ha.server_port) + "/",
            api_key="local-ha-test-token",
            entity_id="light.printer",
            pollInterval=5,
        )
        discovered = admin.post(api, json=dict(command="discover", **connection), timeout=5)
        assert discovered.status_code == 200, discovered.text
        assert discovered.json()["entities"][0]["entity_id"] == "light.printer"
        missing = admin.post(
            api, json=dict(command="test", **dict(connection, entity_id="light.missing")), timeout=5
        )
        assert missing.status_code == 400 and "not found" in missing.json()["error"]
        saved = admin.post(
            base + "/api/settings", json={"plugins": {"octolightHA": connection}}, timeout=10
        )
        assert saved.status_code == 200, saved.text
        wait_for(lambda: admin.get(api, timeout=5).json()["state"] is False)
        assert admin.get(api + "?action=toggle", timeout=5).status_code == 405
        assert HA.calls == []
        changed = admin.post(
            api, json={"command": "setLight", "brightness": 75, "color": "#ff0080"}, timeout=5
        )
        assert changed.status_code == 200, changed.text
        assert HA.calls[-1] == (
            "/api/services/light/turn_on",
            {"entity_id": "light.printer", "brightness_pct": 75, "rgb_color": [255, 0, 128]},
        )
        assert changed.json()["state"] is True
        HA.state = "off"
        wait_for(lambda: reader.get(api, timeout=5).json()["state"] is False, timeout=10)
        restricted = reader.get(base + "/api/settings", timeout=5).json()
        assert restricted["plugins"]["octolightHA"]["api_key"] is None
        assert "local-ha-test-token" not in (tmp_path / "logs/octoprint.log").read_text()
        if installation != "fresh":
            persisted = yaml.safe_load((tmp_path / "config.yaml").read_text())["plugins"]
            for key in (
                "turnOnPrintStart",
                "turnOffPrintEnd",
                "turnOffPrintDelay",
                "turnOffPrintFailure",
                "turnOffPrintCancellation",
                "unknown_legacy_marker",
            ):
                assert persisted["octolightHA"].get(key, storage_defaults.get(key)) == legacy[key]
            assert "ha_light_control" not in persisted
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        output.close()
        ha.shutdown()
        ha.server_close()
