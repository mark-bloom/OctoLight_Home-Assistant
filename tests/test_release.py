"""Release checks must reject mismatched tags and incomplete artifacts."""

import io
import tarfile
from zipfile import ZipFile

import pytest

from scripts.check_release import check_release


@pytest.fixture
def artifacts(tmp_path):
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nversion = "0.3.0"\n')
    dist = tmp_path / "dist"
    dist.mkdir()
    return project, dist


def build_artifacts(dist, wheel_version="0.3.0", source_version="0.3.0", omit=None):
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
        archive.writestr("plugin.dist-info/METADATA", "Version: " + wheel_version + "\n\n")
    source = dict(
        entries,
        **{
            "README.md": b"README",
            "LICENSE": b"License",
            "pyproject.toml": b"",
            "PKG-INFO": ("Version: " + source_version + "\n\n").encode(),
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
