"""Release checks must reject mismatched tags and incomplete artifacts."""

import io
import tarfile
from zipfile import ZipFile

import pytest

from scripts.check_release import check_release
from scripts.release_notes import release_notes


@pytest.fixture
def artifacts(tmp_path):
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname = "OctoLight-Home-Assistant"\nversion = "0.3.0"\n')
    dist = tmp_path / "dist"
    dist.mkdir()
    return project, dist


def build_artifacts(
    dist,
    wheel_version="0.3.0",
    source_version="0.3.0",
    omit=None,
    distribution_name="OctoLight-Home-Assistant",
    entrypoint="octolightHA = octoprint_octolightHA",
    standalone_package=False,
):
    required = (
        "__init__.py",
        "ha.py",
        "lighting.py",
        "gcode.py",
        "templates/octolightHA_navbar.jinja2",
        "templates/octolightHA_settings.jinja2",
        "static/js/octolightHA.js",
        "static/css/octolightHA.css",
    )
    entries = {"octoprint_octolightHA/" + name: b"" for name in required if name != omit}
    with ZipFile(dist / "plugin.whl", "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
        archive.writestr(
            "plugin.dist-info/METADATA",
            "Name: " + distribution_name + "\nVersion: " + wheel_version + "\n\n",
        )
        archive.writestr(
            "plugin.dist-info/entry_points.txt", "[octoprint.plugin]\n" + entrypoint + "\n"
        )
        if standalone_package:
            archive.writestr("octoprint_ha_light_control/__init__.py", "")
    source = dict(
        entries,
        **{
            "README.md": b"README",
            "LICENSE": b"License",
            "pyproject.toml": b"",
            "PKG-INFO": (
                "Name: " + distribution_name + "\nVersion: " + source_version + "\n\n"
            ).encode(),
        },
    )
    with tarfile.open(dist / "plugin.tar.gz", "w:gz") as archive:
        for name, content in source.items():
            member = tarfile.TarInfo("plugin-0.3.0/" + name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))


def test_valid_release(artifacts):
    project, dist = artifacts
    build_artifacts(dist)
    check_release("v0.3.0", project, dist)


def test_tag_must_match_project_version(artifacts):
    project, dist = artifacts
    build_artifacts(dist)
    with pytest.raises(ValueError, match="Tag"):
        check_release("v0.3.1", project, dist)


@pytest.mark.parametrize("option", ["wheel_version", "source_version"])
def test_artifact_versions_must_match_project(artifacts, option):
    project, dist = artifacts
    build_artifacts(dist, **{option: "0.2.2"})
    with pytest.raises(ValueError, match="version"):
        check_release("v0.3.0", project, dist)


def test_missing_ui_asset_is_rejected(artifacts):
    project, dist = artifacts
    build_artifacts(dist, omit="static/js/octolightHA.js")
    with pytest.raises(KeyError):
        check_release("v0.3.0", project, dist)


def test_missing_artifacts_are_rejected(artifacts):
    project, dist = artifacts
    with pytest.raises(ValueError, match="exactly one"):
        check_release("v0.3.0", project, dist)


@pytest.mark.parametrize(
    "option,expected",
    [
        ({"distribution_name": "OctoPrint-HA-Light-Control"}, "name"),
        ({"entrypoint": "ha_light_control = octoprint_ha_light_control"}, "identity"),
        ({"entrypoint": "octolightha = octoprint_octolightHA"}, "identity"),
        ({"standalone_package": True}, "standalone fork"),
    ],
)
def test_standalone_fork_identity_cannot_be_released(artifacts, option, expected):
    project, dist = artifacts
    build_artifacts(dist, **option)
    with pytest.raises(ValueError, match=expected):
        check_release("v0.3.0", project, dist)


def test_release_notes_select_only_the_matching_version(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changes\n\n## 0.3.1\n\nNew fixes\n\n## 0.3.0\n\nFirst release\n")
    assert release_notes("v0.3.1", changelog) == "New fixes\n"
    assert release_notes("v0.3.0", changelog) == "First release\n"


@pytest.mark.parametrize("contents", ["# Changes\n", "## 0.3.0\n\n"])
def test_release_notes_reject_missing_or_empty_entry(tmp_path, contents):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(contents)
    with pytest.raises(ValueError, match="changelog entry"):
        release_notes("v0.3.0", changelog)
