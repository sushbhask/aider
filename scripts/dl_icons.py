#!/usr/bin/env python3
"""
Download Material Design Icons SVGs used in the README and save to local assets.
"""

import os
from pathlib import Path

import requests
from treebeardhq import Log

# Create the directory if it doesn't exist
# Create the directory if it doesn't exist
ICONS_DIR = Path("aider/website/assets/icons")
ICONS_DIR.mkdir(parents=True, exist_ok=True)
Log.debug("Created icons directory", directory=str(ICONS_DIR))

# Icons used in the README.md features section
ICONS = [
    "brain",
    "map-outline",
    "code-tags",
    "source-branch",
    "monitor",
    "image-multiple",
    "microphone",
    "check-all",
    "content-copy",
]


def download_icon(icon_name):
    """Download an SVG icon from Material Design Icons CDN."""
    url = f"https://cdn.jsdelivr.net/npm/@mdi/svg@latest/svg/{icon_name}.svg"
    print(f"Downloading {url}...")
    Log.debug("Downloading icon", icon_name=icon_name, url=url)

    response = requests.get(url)
    if response.status_code != 200:
        print(f"Failed to download {icon_name}.svg: {response.status_code}")
        Log.error("Failed to download icon", icon_name=icon_name, status_code=response.status_code)
        return False

    # Save the SVG file
    output_path = ICONS_DIR / f"{icon_name}.svg"
    with open(output_path, "wb") as f:
        f.write(response.content)

    print(f"Saved {icon_name}.svg to {output_path}")
    Log.debug("Successfully saved icon", icon_name=icon_name, output_path=str(output_path))
    return True


def main():
    print(f"Downloading icons to {ICONS_DIR}")
    Log.info("Starting icon download process", icons_dir=str(ICONS_DIR), icon_count=len(ICONS))

    success_count = 0
    for icon in ICONS:
        if download_icon(icon):
            success_count += 1

    print(f"Successfully downloaded {success_count}/{len(ICONS)} icons")
    Log.info("Completed icon download process", success_count=success_count, total_count=len(ICONS))


if __name__ == "__main__":
    main()
