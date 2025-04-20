#!/usr/bin/env python

import re

from aider.dump import dump  # noqa
from treebeardhq import Log

# Standard tag identifier
# Standard tag identifier
REASONING_TAG = "thinking-content-" + "7bbeb8e1441453ad999a0bbba8a46d4b"
# Output formatting
REASONING_START = "--------------\n► **THINKING**"
REASONING_END = "------------\n► **ANSWER**"


def remove_reasoning_content(res, reasoning_tag):
    """
    Remove reasoning content from text based on tags.

    Args:
        res (str): The text to process
        reasoning_tag (str): The tag name to remove

    Returns:
        str: Text with reasoning content removed
    """
    Log.debug("Starting removal of reasoning content", input_length=len(res) if res else 0, tag=reasoning_tag)
    
    if not reasoning_tag:
        Log.debug("No reasoning tag provided, returning original text")
        return res

    # Try to match the complete tag pattern first
    pattern = f"<{reasoning_tag}>.*?</{reasoning_tag}>"
    original_length = len(res) if res else 0
    res = re.sub(pattern, "", res, flags=re.DOTALL).strip()
    
    # If closing tag exists but opening tag might be missing, remove everything before closing
    # tag
    closing_tag = f"</{reasoning_tag}>"
    if closing_tag in res:
        Log.debug("Found orphaned closing tag", closing_tag=closing_tag)
        # Split on the closing tag and keep everything after it
        parts = res.split(closing_tag, 1)
        res = parts[1].strip() if len(parts) > 1 else res
    
    Log.info("Removed reasoning content", original_length=original_length, new_length=len(res) if res else 0, chars_removed=original_length - (len(res) if res else 0))
    return res


def replace_reasoning_tags(text, tag_name):
    """
    Replace opening and closing reasoning tags with standard formatting.
    Ensures exactly one blank line before START and END markers.

    Args:
        text (str): The text containing the tags
        tag_name (str): The name of the tag to replace

    Returns:
        str: Text with reasoning tags replaced with standard format
    """
    Log.debug("Starting tag replacement", input_length=len(text) if text else 0, tag_name=tag_name)
    
    if not text:
        Log.debug("Empty text provided, returning as is")
        return text

    # Replace opening tag with proper spacing
    original_length = len(text)
    text = re.sub(f"\\s*<{tag_name}>\\s*", f"\n{REASONING_START}\n\n", text)

    # Replace closing tag with proper spacing
    text = re.sub(f"\\s*</{tag_name}>\\s*", f"\n\n{REASONING_END}\n\n", text)
    
    Log.info("Replaced reasoning tags with standard format", original_length=original_length, new_length=len(text), tag_name=tag_name)
    return text


def format_reasoning_content(reasoning_content, tag_name):
    """
    Format reasoning content with appropriate tags.

    Args:
        reasoning_content (str): The content to format
        tag_name (str): The tag name to use

    Returns:
        str: Formatted reasoning content with tags
    """
    Log.debug("Formatting reasoning content", content_length=len(reasoning_content) if reasoning_content else 0, tag_name=tag_name)
    
    if not reasoning_content:
        Log.debug("Empty reasoning content, returning empty string")
        return ""

    formatted = f"<{tag_name}>\n\n{reasoning_content}\n\n</{tag_name}>"
    Log.info("Formatted reasoning content with tags", original_length=len(reasoning_content), formatted_length=len(formatted), tag_name=tag_name)
    return formatted
