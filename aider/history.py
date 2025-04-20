import argparse

from aider import models, prompts
from aider.dump import dump  # noqa: F401
from treebeardhq import Log



class ChatSummary:
    def __init__(self, models=None, max_tokens=1024):
        if not models:
            Log.error("No models provided to ChatSummary")
            raise ValueError("At least one model must be provided")
        self.models = models if isinstance(models, list) else [models]
        self.max_tokens = max_tokens
        self.token_count = self.models[0].token_count
        Log.debug("ChatSummary initialized", models=self.models, max_tokens=self.max_tokens)

    def too_big(self, messages):
        sized = self.tokenize(messages)
        total = sum(tokens for tokens, _msg in sized)
        result = total > self.max_tokens
        Log.debug("Checking if messages are too big", total_tokens=total, max_tokens=self.max_tokens, result=result)
        return result

    def tokenize(self, messages):
        sized = []
        for msg in messages:
            tokens = self.token_count(msg)
            sized.append((tokens, msg))
        Log.debug("Tokenized messages", message_count=len(messages), total_tokens=sum(tokens for tokens, _msg in sized))
        return sized

    def summarize(self, messages, depth=0):
        Log.info("Starting message summarization", message_count=len(messages), depth=depth)
        messages = self.summarize_real(messages)
        if messages and messages[-1]["role"] != "assistant":
            Log.debug("Adding assistant response to end of summary")
            messages.append(dict(role="assistant", content="Ok."))
        Log.info("Summarization complete", final_message_count=len(messages))
        return messages

    def summarize_real(self, messages, depth=0):
        if not self.models:
            Log.error("No models available for summarization")
            raise ValueError("No models available for summarization")

        Log.debug("Starting recursive summarization", message_count=len(messages), depth=depth)
        sized = self.tokenize(messages)
        total = sum(tokens for tokens, _msg in sized)
        
        if total <= self.max_tokens and depth == 0:
            Log.debug("Messages already fit within token limit", total_tokens=total, max_tokens=self.max_tokens)
            return messages

        min_split = 4
        if len(messages) <= min_split or depth > 3:
            Log.debug("Message count too small or max depth reached, summarizing all", message_count=len(messages), depth=depth)
            return self.summarize_all(messages)

        tail_tokens = 0
        split_index = len(messages)
        half_max_tokens = self.max_tokens // 2
        
        Log.debug("Calculating split point for messages", half_max_tokens=half_max_tokens)
        # Iterate over the messages in reverse order
        for i in range(len(sized) - 1, -1, -1):
            tokens, _msg = sized[i]
            if tail_tokens + tokens < half_max_tokens:
                tail_tokens += tokens
                split_index = i
            else:
                break

        # Ensure the head ends with an assistant message
        while messages[split_index - 1]["role"] != "assistant" and split_index > 1:
            split_index -= 1

        if split_index <= min_split:
            Log.debug("Split index too small, summarizing all", split_index=split_index, min_split=min_split)
            return self.summarize_all(messages)

        head = messages[:split_index]
        tail = messages[split_index:]
        
        Log.debug("Split messages into head and tail", head_count=len(head), tail_count=len(tail), split_index=split_index)

        sized = sized[:split_index]
        head.reverse()
        sized.reverse()
        keep = []
        total = 0

        # These sometimes come set with value = None
        model_max_input_tokens = self.models[0].info.get("max_input_tokens") or 4096
        model_max_input_tokens -= 512
        
        Log.debug("Determining which messages to keep", model_max_input_tokens=model_max_input_tokens)
        for i in range(split_index):
            total += sized[i][0]
            if total > model_max_input_tokens:
                break
            keep.append(head[i])

        keep.reverse()
        Log.debug("Keeping subset of head messages", keep_count=len(keep), original_head_count=len(head))

        summary = self.summarize_all(keep)
        Log.debug("Summarized head messages", summary_count=len(summary))

        tail_tokens = sum(tokens for tokens, msg in sized[split_index:])
        summary_tokens = self.token_count(summary)
        
        result = summary + tail
        if summary_tokens + tail_tokens < self.max_tokens:
            Log.debug("Summary and tail fit within token limit", summary_tokens=summary_tokens, tail_tokens=tail_tokens, max_tokens=self.max_tokens)
            return result

        Log.debug("Summary and tail still exceed token limit, recursing", summary_tokens=summary_tokens, tail_tokens=tail_tokens, max_tokens=self.max_tokens)
        return self.summarize_real(result, depth + 1)

    def summarize_all(self, messages):
        Log.debug("Summarizing all messages", message_count=len(messages))
        content = ""
        for msg in messages:
            role = msg["role"].upper()
            if role not in ("USER", "ASSISTANT"):
                continue
            content += f"# {role}\n"
            content += msg["content"]
            if not content.endswith("\n"):
                content += "\n"

        summarize_messages = [
            dict(role="system", content=prompts.summarize),
            dict(role="user", content=content),
        ]

        Log.debug("Attempting summarization with models", model_count=len(self.models))
        for model in self.models:
            try:
                Log.debug("Trying summarization with model", model_name=model.name)
                summary = model.simple_send_with_retries(summarize_messages)
                if summary is not None:
                    summary = prompts.summary_prefix + summary
                    Log.info("Summarization successful", model_name=model.name)
                    return [dict(role="user", content=summary)]
            except Exception as e:
                Log.error("Summarization failed for model", model_name=model.name, error=e)
                print(f"Summarization failed for model {model.name}: {str(e)}")

        Log.error("Summarization failed for all models")
        raise ValueError("summarizer unexpectedly failed for all models")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", help="Markdown file to parse")
    args = parser.parse_args()

    model_names = ["gpt-3.5-turbo", "gpt-4"]  # Add more model names as needed
    model_list = [models.Model(name) for name in model_names]
    summarizer = ChatSummary(model_list)

    with open(args.filename, "r") as f:
        text = f.read()

    summary = summarizer.summarize_chat_history_markdown(text)
    dump(summary)


if __name__ == "__main__":
    main()
