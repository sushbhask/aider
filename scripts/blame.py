#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from operator import itemgetter

import semver
import yaml
from tqdm import tqdm
from treebeardhq import Log



website_files = [
    "aider/website/index.html",
    "aider/website/share/index.md",
    "aider/website/_includes/head_custom.html",
    "aider/website/_includes/home.css",
    "aider/website/docs/leaderboards/index.md",
]

exclude_files = [
    "aider/website/install.ps1",
    "aider/website/install.sh",
]


def blame(start_tag, end_tag=None):
    Log.info("Starting blame analysis", start_tag=start_tag, end_tag=end_tag)
    commits = get_all_commit_hashes_between_tags(start_tag, end_tag)
    commits = [commit[:hash_len] for commit in commits]
    Log.debug("Retrieved commit hashes", count=len(commits))

    authors = get_commit_authors(commits)
    Log.debug("Retrieved commit authors", author_count=len(authors))

    revision = end_tag if end_tag else "HEAD"
    files = run(["git", "ls-tree", "-r", "--name-only", revision]).strip().split("\n")
    test_files = [f for f in files if f.startswith("tests/fixtures/languages/") and "/test." in f]
    files = [
        f
        for f in files
        if f.endswith((".js", ".py", ".scm", ".sh", "Dockerfile", "Gemfile"))
        or (f.startswith(".github/workflows/") and f.endswith(".yml"))
        or (f.startswith("aider/resources/") and f.endswith(".yml"))
        or f in website_files
        or f in test_files
    ]
    files = [f for f in files if not f.endswith("prompts.py")]
    files = [f for f in files if not f.startswith("tests/fixtures/watch")]
    files = [f for f in files if f not in exclude_files]
    Log.debug("Filtered git files", total_files=len(files))

    all_file_counts = {}
    grand_total = defaultdict(int)
    aider_total = 0
    for file in files:
        file_counts = get_counts_for_file(start_tag, end_tag, authors, file)
        if file_counts:
            all_file_counts[file] = file_counts
            for author, count in file_counts.items():
                grand_total[author] += count
                if "(aider)" in author.lower():
                    aider_total += count

    total_lines = sum(grand_total.values())
    aider_percentage = (aider_total / total_lines) * 100 if total_lines > 0 else 0

    end_date = get_tag_date(end_tag if end_tag else "HEAD")
    
    Log.info("Completed blame analysis", 
             start_tag=start_tag, 
             end_tag=end_tag or "HEAD", 
             total_lines=total_lines, 
             aider_total=aider_total, 
             aider_percentage=aider_percentage, 
             file_count=len(all_file_counts))

    return all_file_counts, grand_total, total_lines, aider_total, aider_percentage, end_date


def get_all_commit_hashes_between_tags(start_tag, end_tag=None):
    Log.debug("Getting commit hashes between tags", start_tag=start_tag, end_tag=end_tag)
    if end_tag:
        res = run(["git", "rev-list", f"{start_tag}..{end_tag}"])
    else:
        res = run(["git", "rev-list", f"{start_tag}..HEAD"])

    if res:
        commit_hashes = res.strip().split("\n")
        Log.debug("Retrieved commit hashes", count=len(commit_hashes))
        return commit_hashes


def run(cmd):
    # Get all commit hashes since the specified tag
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        Log.error("Failed to run git command", error=e, cmd=cmd)
        raise


def get_commit_authors(commits):
    Log.debug("Getting commit authors", commit_count=len(commits))
    commit_to_author = dict()
    for commit in commits:
        author = run(["git", "show", "-s", "--format=%an", commit]).strip()
        commit_message = run(["git", "show", "-s", "--format=%s", commit]).strip()
        if commit_message.lower().startswith("aider:"):
            author += " (aider)"
        commit_to_author[commit] = author
    Log.debug("Retrieved commit authors", author_count=len(commit_to_author))
    return commit_to_author


hash_len = len("44e6fefc2")


def process_all_tags_since(start_tag):
    Log.info("Processing all tags since", start_tag=start_tag)
    tags = get_all_tags_since(start_tag)
    # tags += ['HEAD']
    Log.debug("Retrieved tags for processing", tag_count=len(tags))

    results = []
    for i in tqdm(range(len(tags) - 1), desc="Processing tags"):
        start_tag, end_tag = tags[i], tags[i + 1]
        Log.debug("Processing tag pair", start_tag=start_tag, end_tag=end_tag)
        all_file_counts, grand_total, total_lines, aider_total, aider_percentage, end_date = blame(
            start_tag, end_tag
        )
        results.append(
            {
                "start_tag": start_tag,
                "end_tag": end_tag,
                "end_date": end_date.strftime("%Y-%m-%d"),
                "file_counts": all_file_counts,
                "grand_total": {
                    author: count
                    for author, count in sorted(
                        grand_total.items(), key=itemgetter(1), reverse=True
                    )
                },
                "total_lines": total_lines,
                "aider_total": aider_total,
                "aider_percentage": round(aider_percentage, 2),
            }
        )
    Log.info("Completed processing all tags", result_count=len(results))
    return results


def get_latest_version_tag():
    Log.debug("Getting latest version tag")
    all_tags = run(["git", "tag", "--sort=-v:refname"]).strip().split("\n")
    for tag in all_tags:
        if semver.Version.is_valid(tag[1:]) and tag.endswith(".0"):
            Log.debug("Found latest version tag", tag=tag)
            return tag
    Log.warn("No valid version tag found")
    return None


def main():
    Log.info("Starting blame statistics generation")
    parser = argparse.ArgumentParser(description="Get aider/non-aider blame stats")
    parser.add_argument("start_tag", nargs="?", help="The tag to start from (optional)")
    parser.add_argument("--end-tag", help="The tag to end at (default: HEAD)", default=None)
    parser.add_argument(
        "--all-since",
        action="store_true",
        help=(
            "Find all tags since the specified tag and print aider percentage between each pair of"
            " successive tags"
        ),
    )
    parser.add_argument(
        "--output", help="Output file to save the YAML results", type=str, default=None
    )
    args = parser.parse_args()
    Log.debug("Parsed command line arguments", start_tag=args.start_tag, end_tag=args.end_tag, 
             all_since=args.all_since, output=args.output)

    if not args.start_tag:
        args.start_tag = get_latest_version_tag()
        Log.debug("Using latest version tag", start_tag=args.start_tag)
        if not args.start_tag:
            Log.error("No valid vX.Y.0 tag found")
            print("Error: No valid vX.Y.0 tag found.")
            return

    if args.all_since:
        Log.info("Processing all tags since start tag", start_tag=args.start_tag)
        new_results = process_all_tags_since(args.start_tag)
        Log.debug("Processed all tags", result_count=len(new_results))

        # If output file exists, read and update it
        existing_results = []
        if args.output and os.path.exists(args.output):
            Log.debug("Reading existing output file", file=args.output)
            with open(args.output, "r") as f:
                existing_results = yaml.safe_load(f) or []
            Log.debug("Loaded existing results", count=len(existing_results))

        # Create a map of start_tag->end_tag to result for existing entries
        existing_map = {(r["start_tag"], r["end_tag"]): i for i, r in enumerate(existing_results)}
        Log.debug("Created existing results mapping", mapping_size=len(existing_map))

        # Update or append new results
        updated_count = 0
        appended_count = 0
        for new_result in new_results:
            key = (new_result["start_tag"], new_result["end_tag"])
            if key in existing_map:
                # Replace existing entry
                existing_results[existing_map[key]] = new_result
                updated_count += 1
            else:
                # Append new entry
                existing_results.append(new_result)
                appended_count += 1
        Log.debug("Updated and appended results", updated=updated_count, appended=appended_count)

        # Sort results by start_tag
        existing_results.sort(key=lambda x: semver.Version.parse(x["start_tag"][1:]))
        Log.info("Generated all tag comparison results", total_results=len(existing_results))

        yaml_output = yaml.dump(existing_results, sort_keys=True)
    else:
        Log.info("Processing single tag comparison", start_tag=args.start_tag, end_tag=args.end_tag)
        all_file_counts, grand_total, total_lines, aider_total, aider_percentage, end_date = blame(
            args.start_tag, args.end_tag
        )
        Log.debug("Blame statistics generated", total_lines=total_lines, 
                 aider_lines=aider_total, aider_percentage=aider_percentage)

        result = {
            "start_tag": args.start_tag,
            "end_tag": args.end_tag or "HEAD",
            "end_date": end_date.strftime("%Y-%m-%d"),
            "file_counts": all_file_counts,
            "grand_total": {
                author: count
                for author, count in sorted(grand_total.items(), key=itemgetter(1), reverse=True)
            },
            "total_lines": total_lines,
            "aider_total": aider_total,
            "aider_percentage": round(aider_percentage, 2),
        }
        Log.info("Generated single tag comparison result", start_tag=result["start_tag"], 
                end_tag=result["end_tag"], aider_percentage=result["aider_percentage"])

        yaml_output = yaml.dump(result, sort_keys=True)

    if args.output:
        Log.info("Writing results to output file", output_file=args.output)
        with open(args.output, "w") as f:
            f.write(yaml_output)
    else:
        Log.debug("Writing results to stdout")
        print(yaml_output)

    if not args.all_since:
        Log.info("Completed blame analysis", aider_percentage=round(aider_percentage))
        print(f"- Aider wrote {round(aider_percentage)}% of the code in this release.")


def get_counts_for_file(start_tag, end_tag, authors, fname):
    Log.debug("Getting blame counts for file", filename=fname, start_tag=start_tag, end_tag=end_tag)
    try:
        if end_tag:
            text = run(
                [
                    "git",
                    "blame",
                    "-M100",  # Detect moved lines within a file with 100% similarity
                    "-C100",  # Detect moves across files with 100% similarity
                    "-C",  # Increase detection effort
                    "-C",  # Increase detection effort even more
                    "--abbrev=9",
                    f"{start_tag}..{end_tag}",
                    "--",
                    fname,
                ]
            )
        else:
            text = run(
                [
                    "git",
                    "blame",
                    "-M100",  # Detect moved lines within a file with 100% similarity
                    "-C100",  # Detect moves across files with 100% similarity
                    "-C",  # Increase detection effort
                    "-C",  # Increase detection effort even more
                    "--abbrev=9",
                    f"{start_tag}..HEAD",
                    "--",
                    fname,
                ]
            )
        if not text:
            Log.debug("No blame output for file", filename=fname)
            return None
        text = text.splitlines()
        line_counts = defaultdict(int)
        for line in text:
            if line.startswith("^"):
                continue
            hsh = line[:hash_len]
            author = authors.get(hsh, "Unknown")
            line_counts[author] += 1

        Log.debug("File blame completed", filename=fname, total_lines=sum(line_counts.values()))
        return dict(line_counts)
    except subprocess.CalledProcessError as e:
        if "no such path" in str(e).lower():
            # File doesn't exist in this revision range, which is okay
            Log.debug("File not found in revision range", filename=fname)
            return None
        else:
            # Some other error occurred
            Log.error("Error blaming file", filename=fname, error=e)
            print(f"Warning: Unable to blame file {fname}. Error: {e}", file=sys.stderr)
            return None


def get_all_tags_since(start_tag):
    Log.debug("Getting all tags since tag", start_tag=start_tag)
    all_tags = run(["git", "tag", "--sort=v:refname"]).strip().split("\n")
    start_version = semver.Version.parse(start_tag[1:])  # Remove 'v' prefix
    filtered_tags = [
        tag
        for tag in all_tags
        if semver.Version.is_valid(tag[1:]) and semver.Version.parse(tag[1:]) >= start_version
    ]
    result = [tag for tag in filtered_tags if tag.endswith(".0")]
    Log.debug("Found tags since start tag", count=len(result))
    return result


def get_tag_date(tag):
    date_str = run(["git", "log", "-1", "--format=%ai", tag]).strip()
    date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
    Log.debug("Retrieved tag date", tag=tag, date=date.strftime("%Y-%m-%d"))
    return date


if __name__ == "__main__":
    main()
