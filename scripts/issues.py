#!/usr/bin/env python3

import argparse
import os
import re
from collections import defaultdict
from datetime import datetime

import requests
from dotenv import load_dotenv
from tqdm import tqdm
from treebeardhq import Log



def has_been_reopened(issue_number):
    timeline_url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/timeline"
    Log.debug("Fetching issue timeline", issue_number=issue_number, url=timeline_url)
    response = requests.get(timeline_url, headers=headers)
    response.raise_for_status()
    events = response.json()
    reopened = any(event["event"] == "reopened" for event in events if "event" in event)
    Log.debug("Checked issue reopened status", issue_number=issue_number, reopened=reopened, event_count=len(events))
    return reopened


# Load environment variables from .env file
load_dotenv()

BOT_SUFFIX = """

Note: [A bot script](https://github.com/Aider-AI/aider/blob/main/scripts/issues.py) made these updates to the issue.
"""  # noqa

DUPLICATE_COMMENT = (
    """Thanks for trying aider and filing this issue.

This looks like a duplicate of #{oldest_issue_number}. Please see the comments there for more information, and feel free to continue the discussion within that issue.

I'm going to close this issue for now. But please let me know if you think this is actually a distinct issue and I will reopen this issue."""  # noqa
    + BOT_SUFFIX
)

STALE_COMMENT = (
    """I'm labeling this issue as stale because it has been open for 2 weeks with no activity. If there are no additional comments, I will close it in 7 days."""  # noqa
    + BOT_SUFFIX
)

CLOSE_STALE_COMMENT = (
    """I'm closing this issue because it has been stalled for 3 weeks with no activity. Feel free to add a comment here and we can re-open it. Or feel free to file a new issue at any time."""  # noqa
    + BOT_SUFFIX
)

CLOSE_FIXED_ENHANCEMENT_COMMENT = (
    """I'm closing this enhancement request since it has been marked as 'fixed' for over """
    """3 weeks. The requested feature should now be available in recent versions of aider.\n\n"""
    """If you find that this enhancement is still needed, please feel free to reopen this """
    """issue or create a new one.""" + BOT_SUFFIX
)

CLOSE_FIXED_BUG_COMMENT = (
    """I'm closing this bug report since it has been marked as 'fixed' for over """
    """3 weeks. This issue should be resolved in recent versions of aider.\n\n"""
    """If you find that this bug is still present, please feel free to reopen this """
    """issue or create a new one with steps to reproduce.""" + BOT_SUFFIX
)

# GitHub API configuration
GITHUB_API_URL = "https://api.github.com"
REPO_OWNER = "Aider-AI"
REPO_NAME = "aider"
TOKEN = os.getenv("GITHUB_TOKEN")

headers = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github.v3+json"}


def get_issues(state="open"):
    issues = []
    page = 1
    per_page = 100

    # First, get the total count of issues
    Log.info("Fetching initial issues to determine count", state=state)
    response = requests.get(
        f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues",
        headers=headers,
        params={"state": state, "per_page": 1},
    )
    response.raise_for_status()
    total_count = int(response.headers.get("Link", "").split("page=")[-1].split(">")[0])
    total_pages = (total_count + per_page - 1) // per_page
    Log.debug("Calculated pagination details", total_count=total_count, total_pages=total_pages, per_page=per_page)

    with tqdm(total=total_pages, desc="Collecting issues", unit="page") as pbar:
        while True:
            Log.debug("Fetching page of issues", page=page, state=state)
            response = requests.get(
                f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues",
                headers=headers,
                params={"state": state, "page": page, "per_page": per_page},
            )
            response.raise_for_status()
            page_issues = response.json()
            if not page_issues:
                Log.debug("No more issues found", page=page)
                break
            issues.extend(page_issues)
            page += 1
            pbar.update(1)
    Log.info("Completed fetching all issues", total_issues=len(issues), state=state)
    return issues


def group_issues_by_subject(issues):
    grouped_issues = defaultdict(list)
    pattern = r"Uncaught .+ in .+ line \d+"
    Log.debug("Grouping issues by subject", total_issues=len(issues))
    for issue in issues:
        if re.search(pattern, issue["title"]) and not has_been_reopened(issue["number"]):
            subject = issue["title"]
            grouped_issues[subject].append(issue)
    Log.info("Grouped issues by subject", groups_count=len(grouped_issues))
    return grouped_issues


def find_oldest_issue(subject, all_issues):
    oldest_issue = None
    oldest_date = datetime.now()
    Log.debug("Finding oldest issue for subject", subject=subject)

    for issue in all_issues:
        if issue["title"] == subject and not has_been_reopened(issue["number"]):
            created_at = datetime.strptime(issue["created_at"], "%Y-%m-%dT%H:%M:%SZ")
            if created_at < oldest_date:
                oldest_date = created_at
                oldest_issue = issue

    if oldest_issue:
        Log.info("Found oldest issue for subject", 
                issue_number=oldest_issue["number"], 
                created_at=oldest_date.isoformat(),
                state=oldest_issue["state"])
    else:
        Log.warn("No oldest issue found for subject", subject=subject)
    
    return oldest_issue


def comment_and_close_duplicate(issue, oldest_issue):
    # Skip if issue is labeled as priority
    if "priority" in [label["name"] for label in issue["labels"]]:
        Log.info("Skipping priority issue", issue_number=issue["number"])
        print(f"  - Skipping priority issue #{issue['number']}")
        return

    comment_url = (
        f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/comments"
    )
    close_url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}"

    comment_body = DUPLICATE_COMMENT.format(oldest_issue_number=oldest_issue["number"])

    # Post comment
    Log.debug("Posting duplicate comment", issue_number=issue["number"], oldest_issue_number=oldest_issue["number"])
    response = requests.post(comment_url, headers=headers, json={"body": comment_body})
    response.raise_for_status()

    # Close issue
    Log.debug("Closing duplicate issue", issue_number=issue["number"])
    response = requests.patch(close_url, headers=headers, json={"state": "closed"})
    response.raise_for_status()

    Log.info("Commented and closed duplicate issue", 
             issue_number=issue["number"], 
             duplicates_issue=oldest_issue["number"])
    print(f"  - Commented and closed issue #{issue['number']}")


def find_unlabeled_with_paul_comments(issues):
    unlabeled_issues = []
    Log.debug("Finding unlabeled issues with paul-gauthier comments", total_issues=len(issues))
    
    for issue in issues:
        # Skip pull requests
        if "pull_request" in issue:
            continue

        if not issue["labels"] and issue["state"] == "open":
            # Get comments for this issue
            comments_url = (
                f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/comments"
            )
            Log.debug("Fetching comments for unlabeled issue", issue_number=issue["number"])
            response = requests.get(comments_url, headers=headers)
            response.raise_for_status()
            comments = response.json()

            # Check if paul-gauthier has commented
            has_paul_comment = any(comment["user"]["login"] == "paul-gauthier" for comment in comments)
            if has_paul_comment:
                Log.debug("Found paul-gauthier comment on unlabeled issue", 
                          issue_number=issue["number"], 
                          comment_count=len(comments))
                unlabeled_issues.append(issue)
    
    Log.info("Completed finding unlabeled issues with paul-gauthier comments", 
             found_issues=len(unlabeled_issues))
    return unlabeled_issues


def handle_unlabeled_issues(all_issues, auto_yes):
    Log.info("Starting to find unlabeled issues with paul-gauthier comments")
    print("\nFinding unlabeled issues with paul-gauthier comments...")
    unlabeled_issues = [
        issue
        for issue in find_unlabeled_with_paul_comments(all_issues)
        if "priority" not in [label["name"] for label in issue["labels"]]
    ]

    if not unlabeled_issues:
        Log.debug("No unlabeled issues with paul-gauthier comments found")
        print("No unlabeled issues with paul-gauthier comments found.")
        return

    Log.info("Found unlabeled issues with paul-gauthier comments", count=len(unlabeled_issues))
    print(f"\nFound {len(unlabeled_issues)} unlabeled issues with paul-gauthier comments:")
    for issue in unlabeled_issues:
        print(f"  - #{issue['number']}: {issue['title']} {issue['html_url']}")

    if not auto_yes:
        confirm = input("\nDo you want to add the 'question' label to these issues? (y/n): ")
        if confirm.lower() != "y":
            Log.debug("User chose to skip labeling")
            print("Skipping labeling.")
            return

    Log.info("Adding 'question' label to issues", count=len(unlabeled_issues))
    print("\nAdding 'question' label to issues...")
    for issue in unlabeled_issues:
        url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}"
        response = requests.patch(url, headers=headers, json={"labels": ["question"]})
        response.raise_for_status()
        Log.debug("Added 'question' label to issue", issue_number=issue['number'])
        print(f"  - Added 'question' label to #{issue['number']}")


def handle_stale_issues(all_issues, auto_yes):
    Log.info("Starting to check for stale question issues")
    print("\nChecking for stale question issues...")
    stale_issues_count = 0

    for issue in all_issues:
        # Skip if not open, not a question, already stale, or has been reopened
        labels = [label["name"] for label in issue["labels"]]
        if (
            issue["state"] != "open"
            or "question" not in labels
            or "stale" in labels
            or "priority" in labels
            or has_been_reopened(issue["number"])
        ):
            continue

        # Get latest activity timestamp from issue or its comments
        latest_activity = datetime.strptime(issue["updated_at"], "%Y-%m-%dT%H:%M:%SZ")

        # Check if issue is stale (no activity for 14 days)
        days_inactive = (datetime.now() - latest_activity).days
        if days_inactive >= 14:
            stale_issues_count += 1
            Log.info("Found stale issue", issue_number=issue['number'], days_inactive=days_inactive)
            print(f"\nStale issue found: #{issue['number']}: {issue['title']}\n{issue['html_url']}")
            print(f"  No activity for {days_inactive} days")

            if not auto_yes:
                confirm = input("Add stale label and comment? (y/n): ")
                if confirm.lower() != "y":
                    Log.debug("User chose to skip stale issue", issue_number=issue['number'])
                    print("Skipping this issue.")
                    continue

            # Add comment
            comment_url = (
                f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/comments"
            )
            response = requests.post(comment_url, headers=headers, json={"body": STALE_COMMENT})
            response.raise_for_status()

            # Add stale label
            url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}"
            response = requests.patch(url, headers=headers, json={"labels": ["question", "stale"]})
            response.raise_for_status()

            Log.debug("Added stale label and comment", issue_number=issue['number'])
            print(f"  Added stale label and comment to #{issue['number']}")
    
    Log.info("Completed checking for stale issues", stale_issues_found=stale_issues_count)


def handle_stale_closing(all_issues, auto_yes):
    Log.info("Starting to check for issues to close or unstale")
    print("\nChecking for issues to close or unstale...")
    issues_unstaled = 0
    issues_closed = 0

    for issue in all_issues:
        # Skip if not open, not stale, or is priority
        labels = [label["name"] for label in issue["labels"]]
        if issue["state"] != "open" or "stale" not in labels or "priority" in labels:
            continue

        # Get the timeline to find when the stale label was last added
        timeline_url = (
            f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/timeline"
        )
        response = requests.get(timeline_url, headers=headers)
        response.raise_for_status()
        events = response.json()

        # Find the most recent stale label addition
        stale_events = [
            event
            for event in events
            if event.get("event") == "labeled" and event.get("label", {}).get("name") == "stale"
        ]

        if not stale_events:
            continue

        latest_stale = datetime.strptime(stale_events[-1]["created_at"], "%Y-%m-%dT%H:%M:%SZ")

        # Get comments since the stale label
        comments_url = (
            f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/comments"
        )
        response = requests.get(comments_url, headers=headers)
        response.raise_for_status()
        comments = response.json()

        # Check for comments newer than the stale label
        new_comments = [
            comment
            for comment in comments
            if datetime.strptime(comment["created_at"], "%Y-%m-%dT%H:%M:%SZ") > latest_stale
        ]

        if new_comments:
            Log.info("Found new activity on stale issue", 
                     issue_number=issue['number'], comment_count=len(new_comments))
            print(f"\nFound new activity on stale issue #{issue['number']}: {issue['title']}")
            print(f"  {len(new_comments)} new comments since stale label")

            if not auto_yes:
                confirm = input("Remove stale label? (y/n): ")
                if confirm.lower() != "y":
                    Log.debug("User chose to skip unstaling", issue_number=issue['number'])
                    print("Skipping this issue.")
                    continue

            # Remove stale label but keep question label
            url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}"
            response = requests.patch(url, headers=headers, json={"labels": ["question"]})
            response.raise_for_status()
            Log.debug("Removed stale label", issue_number=issue['number'])
            print(f"  Removed stale label from #{issue['number']}")
            issues_unstaled += 1
        else:
            # Check if it's been 7 days since stale label
            days_stale = (datetime.now() - latest_stale).days
            if days_stale >= 7:
                Log.info("Found stale issue ready for closing", 
                         issue_number=issue['number'], days_stale=days_stale)
                print(f"\nStale issue ready for closing #{issue['number']}: {issue['title']}")
                print(f"  No activity for {days_stale} days since stale label")

                if not auto_yes:
                    confirm = input("Close this issue? (y/n): ")
                    if confirm.lower() != "y":
                        Log.debug("User chose to skip closing stale issue", issue_number=issue['number'])
                        print("Skipping this issue.")
                        continue

                # Add closing comment
                comment_url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/comments"  # noqa
                response = requests.post(
                    comment_url, headers=headers, json={"body": CLOSE_STALE_COMMENT}
                )
                response.raise_for_status()

                # Close the issue
                url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}"
                response = requests.patch(url, headers=headers, json={"state": "closed"})
                response.raise_for_status()
                Log.debug("Closed stale issue", issue_number=issue['number'])
                print(f"  Closed issue #{issue['number']}")
                issues_closed += 1


def handle_fixed_issues(all_issues, auto_yes):
    print("\nChecking for fixed enhancement and bug issues to close...")
    Log.info("Starting to check for fixed issues to close", issue_count=len(all_issues))

    issues_processed = 0
    issues_closed = 0

    for issue in all_issues:
        # Skip if not open, doesn't have fixed label, or is priority
        labels = [label["name"] for label in issue["labels"]]
        if issue["state"] != "open" or "fixed" not in labels or "priority" in labels:
            continue

        # Check if it's an enhancement or bug
        is_enhancement = "enhancement" in labels
        is_bug = "bug" in labels
        if not (is_enhancement or is_bug):
            continue

        issues_processed += 1
        
        # Find when the fixed label was added
        timeline_url = (
            f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/timeline"
        )
        response = requests.get(timeline_url, headers=headers)
        response.raise_for_status()
        events = response.json()

        # Find the most recent fixed label addition
        fixed_events = [
            event
            for event in events
            if event.get("event") == "labeled" and event.get("label", {}).get("name") == "fixed"
        ]

        if not fixed_events:
            continue

        latest_fixed = datetime.strptime(fixed_events[-1]["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        days_fixed = (datetime.now() - latest_fixed).days

        if days_fixed >= 21:
            issue_type = "enhancement" if is_enhancement else "bug"
            Log.debug("Found fixed issue ready for closing", 
                     issue_number=issue['number'], 
                     issue_title=issue['title'], 
                     issue_type=issue_type, 
                     days_fixed=days_fixed)
            
            print(f"\nFixed {issue_type} ready for closing #{issue['number']}: {issue['title']}")
            print(f"  Has been marked fixed for {days_fixed} days")

            if not auto_yes:
                confirm = input("Close this issue? (y/n): ")
                if confirm.lower() != "y":
                    print("Skipping this issue.")
                    continue

            # Add closing comment
            comment_url = (
                f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/comments"
            )
            comment = CLOSE_FIXED_ENHANCEMENT_COMMENT if is_enhancement else CLOSE_FIXED_BUG_COMMENT
            response = requests.post(comment_url, headers=headers, json={"body": comment})
            response.raise_for_status()

            # Close the issue
            url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}"
            response = requests.patch(url, headers=headers, json={"state": "closed"})
            response.raise_for_status()
            issues_closed += 1
            Log.info("Closed fixed issue", 
                    issue_number=issue['number'], 
                    issue_type=issue_type, 
                    days_fixed=days_fixed)
            print(f"  Closed issue #{issue['number']}")

    Log.info("Completed fixed issues processing", 
            issues_processed=issues_processed, 
            issues_closed=issues_closed)


def handle_duplicate_issues(all_issues, auto_yes):
    open_issues = [issue for issue in all_issues if issue["state"] == "open"]
    grouped_open_issues = group_issues_by_subject(open_issues)

    Log.info("Starting duplicate issues check", 
            total_open_issues=len(open_issues), 
            subject_groups=len(grouped_open_issues))
    print("Looking for duplicate issues (skipping reopened issues)...")
    
    total_processed = 0
    total_closed = 0
    
    for subject, issues in grouped_open_issues.items():
        oldest_issue = find_oldest_issue(subject, all_issues)
        if not oldest_issue:
            continue

        related_issues = set(issue["number"] for issue in issues)
        related_issues.add(oldest_issue["number"])
        if len(related_issues) <= 1:
            continue

        Log.debug("Found potential duplicate issue group", 
                subject=subject, 
                issue_count=len(issues), 
                oldest_issue_number=oldest_issue["number"])
        
        print(f"\nIssue: {subject}")
        print(f"Open issues: {len(issues)}")
        sorted_issues = sorted(issues, key=lambda x: x["number"], reverse=True)
        for issue in sorted_issues:
            print(f"  - #{issue['number']}: {issue['comments']} comments {issue['html_url']}")

        print(
            f"Oldest issue: #{oldest_issue['number']}: {oldest_issue['comments']} comments"
            f" {oldest_issue['html_url']} ({oldest_issue['state']})"
        )

        if not auto_yes:
            confirm = input("Do you want to comment and close duplicate issues? (y/n): ")
            if confirm.lower() != "y":
                print("Skipping this group of issues.")
                continue

        issues_closed_in_group = 0
        total_processed += len(issues) - 1  # All except oldest

        for issue in issues:
            if issue["number"] != oldest_issue["number"]:
                comment_and_close_duplicate(issue, oldest_issue)
                issues_closed_in_group += 1
                total_closed += 1

        Log.info("Processed duplicate issue group", 
                subject=subject, 
                oldest_issue_number=oldest_issue["number"], 
                issues_closed=issues_closed_in_group)
        
        if oldest_issue["state"] == "open":
            print(f"Oldest issue #{oldest_issue['number']} left open")

    Log.info("Completed duplicate issues processing", 
            total_groups_processed=len(grouped_open_issues), 
            total_issues_closed=total_closed)


def main():
    parser = argparse.ArgumentParser(description="Handle duplicate GitHub issues")
    parser.add_argument(
        "--yes", action="store_true", help="Automatically close duplicates without prompting"
    )
    args = parser.parse_args()

    if not TOKEN:
        Log.error("Missing GitHub token", error="GITHUB_TOKEN environment variable not set")
        print("Error: Missing GITHUB_TOKEN environment variable. Please check your .env file.")
        return

    Log.info("Starting GitHub issue management script", auto_yes=args.yes)
    all_issues = get_issues("all")
    Log.info("Retrieved all issues", count=len(all_issues))

    handle_unlabeled_issues(all_issues, args.yes)
    handle_stale_issues(all_issues, args.yes)
    handle_stale_closing(all_issues, args.yes)
    handle_duplicate_issues(all_issues, args.yes)
    handle_fixed_issues(all_issues, args.yes)
    
    Log.info("GitHub issue management script completed")


if __name__ == "__main__":
    main()
