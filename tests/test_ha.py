from unittest.mock import Mock, patch

import pytest
import requests

from octoprint_octolightHA.ha import HomeAssistant, HomeAssistantError


@pytest.fixture
def client():
    return HomeAssistant(" https://ha.local/ ", "secret")


@pytest.mark.parametrize("status,message", [(401, "token"), (403, "permissions"), (404, "entity"), (500, "500"), (302, "302")])
def test_http_errors(client, status, message):
    with patch("requests.request", return_value=Mock(status_code=status)):
        with pytest.raises(HomeAssistantError, match=message):
            client.state("light.printer")


def test_service_empty_response_and_bounded_request(client):
    response = Mock(status_code=200)
    response.json.return_value = []
    with patch("requests.request", return_value=response) as request:
        assert client.service("switch.printer", "turn_off") == []
    args = request.call_args.kwargs
    assert args["timeout"] == (3.05, 10)
    assert args["allow_redirects"] is False
    assert args["verify"] is True
    assert args["json"] == {"entity_id": "switch.printer"}
    assert request.call_args.args[1] == "https://ha.local/api/services/switch/turn_off"


@pytest.mark.parametrize("entity", ["desk_lamp", "sensor.temperature", "light.bad/path", "", None])
def test_invalid_entity(client, entity):
    with patch("requests.request") as request:
        with pytest.raises(HomeAssistantError, match="complete entity"):
            client.state(entity)
        request.assert_not_called()


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError(), requests.exceptions.SSLError()])
def test_network_errors_do_not_leak_credentials(client, error):
    with patch("requests.request", side_effect=error):
        with pytest.raises(HomeAssistantError) as caught:
            client.state("light.printer")
        assert "secret" not in str(caught.value)


def test_invalid_json(client):
    response = Mock(status_code=200)
    response.json.side_effect = ValueError("secret")
    with patch("requests.request", return_value=response):
        with pytest.raises(HomeAssistantError, match="invalid JSON"):
            client.state("light.printer")


@pytest.mark.parametrize("url", ["", "ha.local", "ftp://ha.local", "http://user:secret@ha.local", "http://ha.local?token=x", "http://ha.local:bad"])
def test_invalid_address(url):
    with pytest.raises(HomeAssistantError):
        HomeAssistant(url, "secret")
