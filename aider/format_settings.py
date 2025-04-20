
from treebeardhq import Log
def scrub_sensitive_info(args, text):
    # Replace sensitive information with last 4 characters
    if text and args.openai_api_key:
        last_4 = args.openai_api_key[-4:]
        text = text.replace(args.openai_api_key, f"...{last_4}")
        Log.debug("Scrubbed OpenAI API key from text")
    if text and args.anthropic_api_key:
        last_4 = args.anthropic_api_key[-4:]
        text = text.replace(args.anthropic_api_key, f"...{last_4}")
        Log.debug("Scrubbed Anthropic API key from text")
    return text


def format_settings(parser, args):
    show = scrub_sensitive_info(args, parser.format_values())
    Log.debug("Retrieved and scrubbed parser values")
    
    # clean up the headings for consistency w/ new lines
    heading_env = "Environment Variables:"
    heading_defaults = "Defaults:"
    if heading_env in show:
        show = show.replace(heading_env, "\n" + heading_env)
        show = show.replace(heading_defaults, "\n" + heading_defaults)
        Log.debug("Formatted headings in settings display")
    
    show += "\n"
    show += "Option settings:\n"
    
    option_count = 0
    for arg, val in sorted(vars(args).items()):
        if val:
            val = scrub_sensitive_info(args, str(val))
            option_count += 1
        show += f"  - {arg}: {val}\n"  # noqa: E221
    
    Log.info("Formatted settings display complete", option_count=option_count)
    return show
