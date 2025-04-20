from dataclasses import dataclass, field
from typing import List
from treebeardhq import Log



@dataclass
class ChatChunks:
    system: List = field(default_factory=list)
    examples: List = field(default_factory=list)
    done: List = field(default_factory=list)
    repo: List = field(default_factory=list)
    readonly_files: List = field(default_factory=list)
    chat_files: List = field(default_factory=list)
    cur: List = field(default_factory=list)
    reminder: List = field(default_factory=list)

    def all_messages(self):
        return (
            self.system
            + self.examples
            + self.readonly_files
            + self.repo
            + self.done
            + self.chat_files
            + self.cur
            + self.reminder
        )

    def add_cache_control_headers(self):
        Log.debug("Adding cache control headers to message chunks")
        if self.examples:
            self.add_cache_control(self.examples)
            Log.debug("Added cache control to examples", examples_count=len(self.examples))
        else:
            self.add_cache_control(self.system)
            Log.debug("Added cache control to system", system_count=len(self.system))

        if self.repo:
            # this will mark both the readonly_files and repomap chunk as cacheable
            self.add_cache_control(self.repo)
            Log.debug("Added cache control to repo", repo_count=len(self.repo))
        else:
            # otherwise, just cache readonly_files if there are any
            self.add_cache_control(self.readonly_files)
            Log.debug("Added cache control to readonly_files", readonly_files_count=len(self.readonly_files))

        self.add_cache_control(self.chat_files)
        Log.debug("Added cache control to chat_files", chat_files_count=len(self.chat_files))
        Log.info("Completed adding cache control headers")

    def add_cache_control(self, messages):
        if not messages:
            Log.debug("No messages to add cache control to")
            return

        content = messages[-1]["content"]
        if type(content) is str:
            Log.debug("Converting string content to dict format")
            content = dict(
                type="text",
                text=content,
            )
        content["cache_control"] = {"type": "ephemeral"}
        
        messages[-1]["content"] = [content]
        Log.debug("Cache control added to message")

    def cacheable_messages(self):
        messages = self.all_messages()
        Log.debug("Finding cacheable messages", total_messages=len(messages))
        for i, message in enumerate(reversed(messages)):
            if isinstance(message.get("content"), list) and message["content"][0].get(
                "cache_control"
            ):
                cacheable_count = len(messages) - i
                Log.debug("Found cacheable messages boundary", cacheable_count=cacheable_count, total_count=len(messages))
                return messages[: len(messages) - i]
        Log.debug("All messages are cacheable")
        return messages
