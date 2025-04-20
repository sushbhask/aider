from aider import diffs

from ..dump import dump  # noqa: F401
from .base_coder import Coder
from .single_wholefile_func_prompts import SingleWholeFileFunctionPrompts
from treebeardhq import Log



class SingleWholeFileFunctionCoder(Coder):
    edit_format = "func"

    functions = [
        dict(
            name="write_file",
            description="write new content into the file",
            # strict=True,
            parameters=dict(
                type="object",
                properties=dict(
                    explanation=dict(
                        type="string",
                        description=(
                            "Step by step plan for the changes to be made to the code (future"
                            " tense, markdown format)"
                        ),
                    ),
                    content=dict(
                        type="string",
                        description="Content to write to the file",
                    ),
                ),
                required=["explanation", "content"],
                additionalProperties=False,
            ),
        ),
    ]

    def __init__(self, *args, **kwargs):
        self.gpt_prompts = SingleWholeFileFunctionPrompts()
        super().__init__(*args, **kwargs)

    def add_assistant_reply_to_cur_messages(self, edited):
        if edited:
            self.cur_messages += [
                dict(role="assistant", content=self.gpt_prompts.redacted_edit_message)
            ]
        else:
            self.cur_messages += [dict(role="assistant", content=self.partial_response_content)]
        Log.debug("Added assistant reply to messages", edited=edited, message_count=len(self.cur_messages))

    def render_incremental_response(self, final=False):
        res = ""
        if self.partial_response_content:
            res += self.partial_response_content

        args = self.parse_partial_args()

        if not args:
            Log.debug("No args parsed from partial response")
            return ""

        for k, v in args.items():
            res += "\n"
            res += f"{k}:\n"
            res += v

        Log.debug("Rendered incremental response", final=final, args_count=len(args) if args else 0)
        return res

    def live_diffs(self, fname, content, final):
        Log.debug("Generating live diffs", filename=fname, final=final)
        lines = content.splitlines(keepends=True)

        # ending an existing block
        full_path = self.abs_root_path(fname)

        content = self.io.read_text(full_path)
        if content is None:
            orig_lines = []
            Log.debug("File does not exist, using empty original content", filename=fname)
        else:
            orig_lines = content.splitlines()

        show_diff = diffs.diff_partial_update(
            orig_lines,
            lines,
            final,
            fname=fname,
        ).splitlines()

        Log.debug("Generated diff", diff_line_count=len(show_diff))
        return "\n".join(show_diff)

    def get_edits(self):
        chat_files = self.get_inchat_relative_files()
        assert len(chat_files) == 1, chat_files

        args = self.parse_partial_args()
        if not args:
            Log.debug("No args parsed, returning empty edits")
            return []

        res = chat_files[0], args["content"]
        dump(res)
        Log.info("Generated edit", filename=chat_files[0], content_length=len(args["content"]) if args.get("content") else 0)
        return [res]

    def apply_edits(self, edits):
        Log.info("Applying edits", edit_count=len(edits))
        for path, content in edits:
            full_path = self.abs_root_path(path)
            self.io.write_text(full_path, content)
            Log.debug("Applied edit to file", path=path, full_path=full_path, content_length=len(content))
