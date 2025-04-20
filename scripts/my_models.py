#!/usr/bin/env python3

import json
from collections import defaultdict, deque
from pathlib import Path
from treebeardhq import Log



def collect_model_stats(n_lines=1000):
    """Collect model usage statistics from the analytics file."""
    analytics_path = Path.home() / ".aider" / "analytics.jsonl"
    model_stats = defaultdict(int)

    Log.debug("Starting model stats collection", n_lines=n_lines, analytics_path=str(analytics_path))
    
    with open(analytics_path) as f:
        lines = deque(f, n_lines)
        line_count = len(lines)
        Log.debug("Read lines from analytics file", line_count=line_count)
        
        processed_count = 0
        error_count = 0
        
        for line in lines:
            try:
                event = json.loads(line)
                if event["event"] == "message_send":
                    properties = event["properties"]
                    main_model = properties.get("main_model")

                    total_tokens = properties.get("total_tokens", 0)
                    if main_model == "deepseek/deepseek-coder":
                        main_model = "deepseek/deepseek-chat"
                    if main_model:
                        model_stats[main_model] += total_tokens
                        processed_count += 1
            except json.JSONDecodeError:
                error_count += 1
                continue

    Log.info("Completed model stats collection", 
             model_count=len(model_stats), 
             processed_events=processed_count, 
             parse_errors=error_count, 
             total_tokens=sum(model_stats.values()))
    return model_stats


def format_text_table(model_stats):
    """Format model statistics as a text table."""
    total_tokens = sum(model_stats.values())
    lines = []

    Log.debug("Formatting text table for model stats", model_count=len(model_stats), total_tokens=total_tokens)
    
    lines.append("\nModel Token Usage Summary:")
    lines.append("-" * 80)
    lines.append(f"{'Model Name':<40} {'Total Tokens':>15} {'Percent':>10}")
    lines.append("-" * 80)

    for model, tokens in sorted(model_stats.items(), key=lambda x: x[1], reverse=True):
        percentage = (tokens / total_tokens) * 100 if total_tokens > 0 else 0
        lines.append(f"{model:<40} {tokens:>15,} {percentage:>9.1f}%")

    lines.append("-" * 80)
    lines.append(f"{'TOTAL':<40} {total_tokens:>15,} {100:>9.1f}%")

    Log.debug("Text table formatting complete", line_count=len(lines))
    return "\n".join(lines)


def format_html_table(model_stats):
    """Format model statistics as an HTML table."""
    total_tokens = sum(model_stats.values())

    Log.debug("Formatting HTML table for model stats", model_count=len(model_stats), total_tokens=total_tokens)
    
    html = [
        "<style>",
        "table { border-collapse: collapse; width: 100%; }",
        "th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }",
        "th { background-color: #f2f2f2; }",
        "tr:hover { background-color: #f5f5f5; }",
        ".right { text-align: right; }",
        "</style>",
        "<table>",
        (
            "<tr><th>Model Name</th><th class='right'>Total Tokens</th><th"
            " class='right'>Percent</th></tr>"
        ),
    ]

    for model, tokens in sorted(model_stats.items(), key=lambda x: x[1], reverse=True):
        percentage = (tokens / total_tokens) * 100 if total_tokens > 0 else 0
        html.append(
            f"<tr><td>{model}</td>"
            f"<td class='right'>{tokens:,}</td>"
            f"<td class='right'>{percentage:.1f}%</td></tr>"
        )

    html.append("</table>")

    has_redacted = any("REDACTED" in model for model in model_stats.keys())
    # Add note about redacted models if any are present
    if has_redacted:
        Log.debug("Adding redacted models note to HTML output")
        html.extend(
            [
                "",
                "{: .note :}",
                "Some models show as REDACTED, because they are new or unpopular models.",
                'Aider\'s analytics only records the names of "well known" LLMs.',
            ]
        )

    Log.debug("HTML table formatting complete", line_count=len(html), has_redacted_models=has_redacted)
    return "\n".join(html)


if __name__ == "__main__":
    stats = collect_model_stats()
    Log.info("Generated model stats summary", model_count=len(stats), total_tokens=sum(stats.values()))
    print(format_text_table(stats))
