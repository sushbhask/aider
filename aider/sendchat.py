from aider.dump import dump  # noqa: F401
from aider.utils import format_messages
from treebeardhq import Log



def sanity_check_messages(messages):
    """Check if messages alternate between user and assistant roles.
    System messages can be interspersed anywhere.
    Also verifies the last non-system message is from the user.
    Returns True if valid, False otherwise."""
    Log.debug("Starting sanity check on messages", message_count=len(messages))
    last_role = None
    last_non_system_role = None

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            continue

        if last_role and role == last_role:
            turns = format_messages(messages)
            Log.error("Messages validation failed: consecutive non-system messages with same role", 
                     last_role=last_role, current_role=role)
            raise ValueError("Messages don't properly alternate user/assistant:\n\n" + turns)

        last_role = role
        last_non_system_role = role

    # Ensure last non-system message is from user
    is_valid = last_non_system_role == "user"
    Log.debug("Completed sanity check on messages", 
             is_valid=is_valid, last_non_system_role=last_non_system_role)
    return is_valid


def ensure_alternating_roles(messages):
    """Ensure messages alternate between 'assistant' and 'user' roles.

    Inserts empty messages of the opposite role when consecutive messages
    of the same role are found.

    Args:
        messages: List of message dictionaries with 'role' and 'content' keys.

    Returns:
        List of messages with alternating roles.
    """
    if not messages:
        Log.debug("No messages to fix, returning empty list")
        return messages

    fixed_messages = []
    prev_role = None
    inserted_count = 0

    for msg in messages:
        current_role = msg.get("role")  # Get 'role', None if missing

        # If current role same as previous, insert empty message
        # of the opposite role
        if current_role == prev_role:
            if current_role == "user":
                fixed_messages.append({"role": "assistant", "content": ""})
                Log.debug("Inserted empty assistant message between consecutive user messages")
                inserted_count += 1
            else:
                fixed_messages.append({"role": "user", "content": ""})
                Log.debug("Inserted empty user message between consecutive assistant messages")
                inserted_count += 1

        fixed_messages.append(msg)
        prev_role = current_role

    Log.info("Completed alternating role enforcement", 
            original_count=len(messages), 
            inserted_count=inserted_count, 
            final_count=len(fixed_messages))
    return fixed_messages
