"""Print the changelog entry for a release tag, failing if it is missing or empty."""

import os
import re
from pathlib import Path


def release_notes(tag, changelog=Path("CHANGELOG.md")):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError(f"Unsupported release tag: {tag!r}")
    sections = re.split(r"^## ", changelog.read_text(encoding="utf-8"), flags=re.M)
    for section in sections[1:]:
        version, _, body = section.partition("\n")
        if version.strip() == tag[1:]:
            if not body.strip():
                raise ValueError(f"Empty changelog entry for {tag}")
            return body.strip() + "\n"
    raise ValueError(f"Missing changelog entry for {tag}")


if __name__ == "__main__":
    print(release_notes(os.environ["GITHUB_REF_NAME"]), end="")
