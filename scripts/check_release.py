"""Check a tag and built distributions before creating a draft GitHub release."""

import email
import os
import tarfile
from pathlib import Path
from zipfile import ZipFile

try:
    import tomllib
except ImportError:
    import tomli as tomllib


def check_release(tag, project_file=Path("pyproject.toml"), dist=Path("dist")):
    version = tomllib.loads(project_file.read_text())["project"]["version"]
    if tag != "v" + version:
        raise ValueError(f"Tag {tag!r} must match project version v{version}")
    wheels, sources = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Expected exactly one wheel and one source archive")
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
    with ZipFile(wheels[0]) as archive:
        for name in required:
            archive.getinfo("octoprint_octolightHA/" + name)
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        if email.message_from_bytes(archive.read(metadata_name))["Version"] != version:
            raise ValueError("Wheel version differs from project version")
    with tarfile.open(sources[0]) as archive:
        entries = archive.getnames()
        root = entries[0].split("/")[0] + "/"
        for name in ("README.md", "LICENSE", "pyproject.toml"):
            archive.getmember(root + name)
        for name in required:
            archive.getmember(root + "octoprint_octolightHA/" + name)
        metadata = email.message_from_bytes(archive.extractfile(root + "PKG-INFO").read())
        if metadata["Version"] != version:
            raise ValueError("Source archive version differs from project version")
    print(f"Verified release {tag}: wheel and source archive version, backend and UI assets")


if __name__ == "__main__":
    check_release(os.environ["GITHUB_REF_NAME"])
