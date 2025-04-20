#!/usr/bin/env python3

import json
import os
import sys
import time

import requests
from treebeardhq import Log



def get_default_branch(owner, repo):
    """Get the default branch of a GitHub repository using the API."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        default_branch = response.json().get("default_branch")
        Log.debug("Fetched default branch from GitHub API", owner=owner, repo=repo, default_branch=default_branch)
        return default_branch
    except requests.exceptions.RequestException as e:
        Log.warn("Failed to get default branch from GitHub API", owner=owner, repo=repo, error=e)
        return None


def try_download_tags(owner, repo, branch, directory, output_path):
    """Try to download tags.scm from a specific branch."""
    base_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}"
    if directory:
        tags_url = f"{base_url}/{directory}/queries/tags.scm"
    else:
        tags_url = f"{base_url}/queries/tags.scm"

    Log.debug("Attempting to download tags from URL", owner=owner, repo=repo, branch=branch, url=tags_url)
    try:
        response = requests.get(tags_url)
        response.raise_for_status()

        # Save the file
        with open(output_path, "w") as f:
            f.write(response.text)
        Log.info("Successfully downloaded and saved tags file", owner=owner, repo=repo, branch=branch, output_path=output_path)
        return True
    except requests.exceptions.RequestException as e:
        Log.debug("Failed to download tags", owner=owner, repo=repo, branch=branch, error=e)
        return False


def main():
    # Path to the language definitions file
    lang_def_path = "../../tmp/tree-sitter-language-pack/sources/language_definitions.json"

    # Path to store the tags.scm files
    output_dir = "aider/queries/tree-sitter-language-pack"

    # Create the output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Common branch names to try if API fails and config branch doesn't work
    common_branches = ["main", "master", "dev", "develop"]

    try:
        # Load the language definitions
        with open(lang_def_path, "r") as f:
            lang_defs = json.load(f)
        Log.info("Loaded language definitions", file_path=lang_def_path, language_count=len(lang_defs))
    except Exception as e:
        Log.error("Error loading language definitions", file_path=lang_def_path, error=e)
        print(f"Error loading language definitions: {e}")
        sys.exit(1)

    print(f"Found {len(lang_defs)} language definitions")

    # Process each language
    successes = 0
    total = len(lang_defs)

    for lang, config in lang_defs.items():
        # Extract repo URL from the config
        repo_url = config.get("repo")
        Log.debug("Processing language", language=lang, repo_url=repo_url)
        print(f"Processing {lang} ({repo_url})...")

        if not repo_url:
            Log.warn("Skipping language due to missing repository URL", language=lang)
            print(f"Skipping {lang}: No repository URL found")
            continue

        directory = config.get("directory", "")

        # Parse the GitHub repository URL
        if "github.com" not in repo_url:
            Log.warn("Skipping non-GitHub repository", language=lang, repo_url=repo_url)
            print(f"Skipping {lang}: Not a GitHub repository")
            continue

        # Extract the owner and repo name from the URL
        parts = repo_url.rstrip("/").split("/")
        if len(parts) < 5:
            Log.warn("Skipping due to invalid GitHub URL format", language=lang, repo_url=repo_url, url_parts=parts)
            print(f"Skipping {lang}: Invalid GitHub URL format")
            continue

        owner = parts[-2]
        repo = parts[-1]
        Log.debug("Extracted GitHub repository info", language=lang, owner=owner, repo=repo)

        # Create output directory and set output file path
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{lang}-tags.scm")

        # Skip if file already exists
        if os.path.exists(output_file):
            Log.debug("Skipping existing tags file", language=lang, output_file=output_file)
            print(f"Skipping {lang}: tags.scm already exists")
            successes += 1
            continue

        # Try branches in this order:
        # 1. Branch specified in the config
        # 2. Default branch from GitHub API
        # 3. Common branch names (main, master, etc.)

        branches_to_try = []

        # 1. Branch from config (if specified)
        config_branch = config.get("branch")
        if config_branch:
            branches_to_try.append(config_branch)

        # 2. Default branch from GitHub API
        default_branch = get_default_branch(owner, repo)
        if default_branch and default_branch not in branches_to_try:
            branches_to_try.append(default_branch)

        # 3. Add common branch names
        for branch in common_branches:
            if branch not in branches_to_try:
                branches_to_try.append(branch)

        Log.debug("Prepared branch list to try", language=lang, branches=branches_to_try)

        # Try each branch
        success = False
        for branch in branches_to_try:
            if try_download_tags(owner, repo, branch, directory, output_file):
                print(f"Successfully downloaded tags for {lang} (branch: {branch})")
                success = True
                successes += 1
                break

        if not success:
            Log.warn("Failed to download tags after trying all branches", language=lang, tried_branches=branches_to_try)
            print(f"Failed to download tags for {lang} after trying all branches")

        # Be nice to GitHub's API
        time.sleep(0.1)

    Log.info("Language tags processing completed", total_languages=total, successful_downloads=successes)
    print(f"All language tags processed. Downloaded {successes}/{total} successfully.")


if __name__ == "__main__":
    main()
