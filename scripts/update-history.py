#!/usr/bin/env python3

import os
import re
import subprocess
import tempfile

from history_prompts import history_prompt
from treebeardhq import Log



def get_latest_version_from_history():
    with open("HISTORY.md", "r") as f:
        history_content = f.read()

    # Find most recent version header
    match = re.search(r"### Aider v(\d+\.\d+\.\d+)", history_content)
    if not match:
        Log.error("Could not find version header in HISTORY.md")
        raise ValueError("Could not find version header in HISTORY.md")
    Log.debug("Found latest version in HISTORY.md", version=match.group(1))
    return match.group(1)


def run_git_log():
    latest_ver = get_latest_version_from_history()
    cmd = [
        "git",
        "log",
        "--pretty=full",
        f"v{latest_ver}..HEAD",
        "--",
        "aider/",
        ":!aider/website/",
        ":!scripts/",
        ":!HISTORY.md",
    ]
    Log.debug("Running git log command", command=cmd, latest_version=latest_ver)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout


def run_git_diff():
    latest_ver = get_latest_version_from_history()
    cmd = [
        "git",
        "diff",
        f"v{latest_ver}..HEAD",
        "--",
        "aider/",
        ":!aider/website/",
        ":!scripts/",
        ":!HISTORY.md",
    ]
    Log.debug("Running git diff command", command=cmd, latest_version=latest_ver)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout


def run_plain_git_log():
    latest_ver = get_latest_version_from_history()
    cmd = [
        "git",
        "log",
        f"v{latest_ver}..HEAD",
        "--",
        "aider/",
        ":!aider/website/",
        ":!scripts/",
        ":!HISTORY.md",
    ]
    Log.debug("Running plain git log command", command=cmd, latest_version=latest_ver)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout


def main():
    Log.info("Starting release history update process")
    # Get the git log and diff output
    log_content = run_git_log()
    plain_log_content = run_plain_git_log()
    diff_content = run_git_diff()

    # Extract relevant portion of HISTORY.md
    latest_ver = get_latest_version_from_history()
    with open("HISTORY.md", "r") as f:
        history_content = f.read()

    # Find the section for this version
    version_header = f"### Aider v{latest_ver}"
    start_idx = history_content.find("# Release history")
    if start_idx == -1:
        Log.error("Could not find start of release history in HISTORY.md")
        raise ValueError("Could not find start of release history")

    # Find where this version's section ends
    version_idx = history_content.find(version_header, start_idx)
    if version_idx == -1:
        Log.error("Could not find version header in HISTORY.md", version_header=version_header)
        raise ValueError(f"Could not find version header: {version_header}")

    # Find the next version header after this one
    next_version_idx = history_content.find("\n### Aider v", version_idx + len(version_header))
    if next_version_idx == -1:
        # No next version found, use the rest of the file
        Log.debug("No next version found, using remainder of file")
        relevant_history = history_content[start_idx:]
    else:
        # Extract just up to the next version
        Log.debug("Found next version header", position=next_version_idx)
        relevant_history = history_content[start_idx:next_version_idx]

    # Save relevant portions to temporary files
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as tmp_log:
        tmp_log.write(log_content)
        log_path = tmp_log.name

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".diff") as tmp_diff:
        tmp_diff.write(diff_content)
        diff_path = tmp_diff.name

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".plain_log") as tmp_plain_log:
        tmp_plain_log.write(plain_log_content)
        plain_log_path = tmp_plain_log.name

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md") as tmp_hist:
        tmp_hist.write(relevant_history)
        hist_path = tmp_hist.name
        
    Log.debug("Created temporary files for processing", 
              log_path=log_path, 
              diff_path=diff_path, 
              plain_log_path=plain_log_path, 
              hist_path=hist_path)

    # Run blame to get aider percentage
    Log.debug("Running blame script to get aider percentage")
    blame_result = subprocess.run(["python3", "scripts/blame.py"], capture_output=True, text=True)
    aider_line = blame_result.stdout.strip().split("\n")[-1]  # Get last line with percentage
    Log.debug("Got aider percentage", aider_line=aider_line)

    # Construct and run the aider command
    message = history_prompt.format(aider_line=aider_line)

    cmd = [
        "aider",
        hist_path,
        "--read",
        log_path,
        "--read",
        plain_log_path,
        "--read",
        diff_path,
        "--msg",
        message,
        "--no-git",
        "--no-auto-lint",
    ]
    Log.debug("Running aider command", command=cmd)
    subprocess.run(cmd)

    # Read back the updated history
    with open(hist_path, "r") as f:
        updated_history = f.read()

    # Find where the next version section would start
    if next_version_idx == -1:
        # No next version found, use the rest of the file
        Log.debug("No next version found, appending updated history to start")
        full_history = history_content[:start_idx] + updated_history
    else:
        # Splice the updated portion back in between the unchanged parts
        Log.debug("Splicing updated history between unchanged parts")
        full_history = (
            history_content[:start_idx]
            + updated_history  # Keep unchanged header
            + history_content[next_version_idx:]  # Add updated portion  # Keep older entries
        )

    # Write back the full history
    Log.debug("Writing updated history back to HISTORY.md")
    with open("HISTORY.md", "w") as f:
        f.write(full_history)

    # Run update-docs.sh after aider
    Log.debug("Running update-docs.sh script")
    subprocess.run(["scripts/update-docs.sh"])

    # Cleanup
    Log.debug("Cleaning up temporary files")
    os.unlink(log_path)
    os.unlink(plain_log_path)
    os.unlink(diff_path)
    os.unlink(hist_path)

    # Show git diff of HISTORY.md
    Log.debug("Showing git diff of HISTORY.md")
    subprocess.run(["git", "diff", "HISTORY.md"])
    
    Log.info("Release history update completed successfully", latest_version=latest_ver)


if __name__ == "__main__":
    main()
