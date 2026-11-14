"""Checks a release tag against the plugin's version, and writes the release's notes.

Used by both release workflows (.gitea/workflows/release.yml and .github/workflows/release.yml):
    python3 scripts/release_notes.py <tag> <owner/repo on GitHub> <notes file>
(the tag is v<version>, whether the release was started from the Run workflow button or by pushing a tag).
The notes always point at the public copy on GitHub, also in a release made on Gitea.

1. The tag must name the version in package.json and py_modules/romm_deck/__init__.py (a leading "v" and
   letter case are ignored, so v0.5.0-Beta matches 0.5.0-beta). A mismatch fails the release, so a zip is
   never published under the wrong version.
2. The notes are short install steps, with the zip's download link for Decky's "Install plugin from URL"
   (a link to the zip itself: the release page's own address is a web page, and Decky stops on it at
   "Parsing zip file"), then that version's section of CHANGELOG.md. Links in the changelog are relative to
   the repository; they're made absolute (at the tag) so they work on the release page.

Prints, for the workflow: "prerelease=true" or "prerelease=false" (versions with a suffix, like 0.5.0-beta,
are published as pre-releases), and "title=..." (v0.5.0-beta -> "V0.5.0 Beta", v0.6.0 -> "V0.6.0").
Exits non-zero, with the reason, when the release must not go ahead.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def plugin_versions():
    """The version in package.json and the one in the backend; they must agree."""
    package = json.loads((ROOT / "package.json").read_text())["version"]
    init = (ROOT / "py_modules/romm_deck/__init__.py").read_text()
    match = re.search(r'^__version__ = "([^"]+)"', init, re.M)
    backend = match[1] if match else None
    return package, backend


def changelog_section(version):
    """CHANGELOG.md's section for `version` (the text under "## <version> (date)"), or None.
    The version has to match the heading's whole version: 0.5.0 doesn't take 0.5.0-beta's section."""
    text = (ROOT / "CHANGELOG.md").read_text()
    heading = re.compile(rf"^## {re.escape(version)}(?=\s|$).*$", re.M | re.I)
    start = heading.search(text)
    if not start:
        return None
    following = re.compile(r"^## ", re.M).search(text, start.end())
    end = following.start() if following else len(text)
    return text[start.end():end].strip()


def absolute_links(text, repo, tag):
    """Relative links (README.md#documentation, ARCHITECTURE.md...) as links to the repository at the tag."""
    def fix(m):
        """One markdown link: kept if it's already absolute or within the page, else pointed at the tag."""
        target = m[2]
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            return m[0]  # already absolute, or a link within the page
        path, _, anchor = target.partition("#")
        if path in ("", "README.md"):
            url = f"https://github.com/{repo}/tree/{tag}"
        else:
            url = f"https://github.com/{repo}/blob/{tag}/{path}"
        return f"[{m[1]}]({url}{'#' + anchor if anchor else ''})"
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", fix, text)


def release_title(version):
    """The release's name: 0.5.0-beta -> "V0.5.0 Beta", 0.6.0 -> "V0.6.0"."""
    number, _, suffix = version.partition("-")
    return f"V{number} {suffix.capitalize()}" if suffix else f"V{number}"


def main():
    """Check the tag, write the notes file, and tell the workflow the release's title and whether it's a
    pre-release."""
    tag, repo, notes_file = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    package, backend = plugin_versions()
    if package != backend:
        sys.exit(f"package.json says {package} but romm_deck/__init__.py says {backend}: make them match first")
    if version.lower() != package.lower():
        sys.exit(f"{version} isn't the plugin's version ({package}): release {package}, or change the version first")
    section = changelog_section(package)
    if not section:
        sys.exit(f"CHANGELOG.md has no section for {package}: add one first")

    zip_url = f"https://github.com/{repo}/releases/download/{tag}/romm-deck.zip"
    install = (
        "## Install\n\n"
        "1. In Game Mode: Decky settings → **Developer mode** on → Developer → **Install plugin from URL**, and "
        f"enter:\n\n   ```\n   {zip_url}\n   ```\n\n"
        "   (or download **romm-deck.zip** below and use **Install plugin from ZIP**).\n"
        "2. In RomM's web UI, create a client API token and choose **Pair device**, then enter your RomM address "
        "and the code in RomM Deck. [Installation](docs/Installation.md) lists the token's permissions.\n\n"
    )
    notes = install + "## What's in it\n\n" + section + "\n"
    notes_file.write_text(absolute_links(notes, repo, tag))
    print(f"prerelease={'true' if '-' in package else 'false'}")
    print(f"title={release_title(package)}")


if __name__ == "__main__":
    main()
