from aider import diffs

from ..dump import dump  # noqa: F401
from .base_coder import Coder
from .wholefile_func_prompts import WholeFileFunctionPrompts
from treebeardhq import Log



class WholeFileFunctionCoder(Coder):
    functions = [
        dict(
            name="write_file",
            description="create or update one or more files",
            parameters=dict(
                type="object",
                required=["explanation", "files"],
                properties=dict(
                    explanation=dict(
                        type="string",
                        description=(
                            "Step by step plan for the changes to be made to the code (future"
                            " tense, markdown format)"
                        ),
                    ),
                    files=dict(
                        type="array",
                        items=dict(
                            type="object",
                            required=["path", "content"],
                            properties=dict(
                                path=dict(
                                    type="string",
                                    description="Path of file to write",
                                ),
                                content=dict(
                                    type="string",
                                    description="Content to write to the file",
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ]

    def __init__(self, *args, **kwargs):
        raise RuntimeError("Deprecated, needs to be refactored to support get_edits/apply_edits")

        self.gpt_prompts = WholeFileFunctionPrompts()
        super().__init__(*args, **kwargs)

    def add_assistant_reply_to_cur_messages(self, edited):
        Log.debug("Adding assistant reply to current messages", edited=edited)
        if edited:
            self.cur_messages += [
                dict(role="assistant", content=self.gpt_prompts.redacted_edit_message)
            ]
        else:
            self.cur_messages += [dict(role="assistant", content=self.partial_response_content)]
        Log.info("Assistant reply added to messages", message_count=len(self.cur_messages))

    def render_incremental_response(self, final=False):
        Log.debug("Rendering incremental response", final=final)
        if self.partial_response_content:
            return self.partial_response_content

        args = self.parse_partial_args()

        if not args:
            Log.debug("No args found for incremental response")
            return

        explanation = args.get("explanation")
        files = args.get("files", [])
        Log.debug("Parsed args for incremental response", explanation_exists=bool(explanation), file_count=len(files))

        res = ""
        if explanation:
            res += f"{explanation}\n\n"

        for i, file_upd in enumerate(files):
            path = file_upd.get("path")
            if not path:
                Log.warn("File update missing path", file_update=file_upd)
                continue
            content = file_upd.get("content")
            if not content:
                Log.warn("File update missing content", path=path)
                continue

            this_final = (i < len(files) - 1) or final
            Log.debug("Generating live diff", path=path, is_final=this_final)
            res += self.live_diffs(path, content, this_final)

        Log.info("Incremental response rendered", response_length=len(res), file_count=len(files))
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
            Log.debug("Read original file content", filename=fname, line_count=len(orig_lines))

        try:
            show_diff = diffs.diff_partial_update(
                orig_lines,
                lines,
                final,
                fname=fname,
            ).splitlines()
            Log.debug("Diff generated successfully", diff_line_count=len(show_diff))
            return "\n".join(show_diff)
        except Exception as e:
            Log.error("Error generating diff", error=e, filename=fname)
            raise

    def _update_files(self):
        Log.debug("Starting file update process")
        name = self.partial_response_function_call.get("name")
        if name and name != "write_file":
            Log.error("Invalid function call name", name=name)
            raise ValueError(f'Unknown function_call name="{name}", use name="write_file"')

        args = self.parse_partial_args()
        if not args:
            Log.debug("No args found for file update")
            return

        files = args.get("files", [])
        Log.debug("Processing file updates", file_count=len(files))

        edited = set()
        for file_upd in files:
            path = file_upd.get("path")
            if not path:
                Log.error("Missing path in file update", file_update=file_upd)
                raise ValueError(f"Missing path parameter: {file_upd}")

            content = file_upd.get("content")
            if not content:
                Log.error("Missing content in file update", path=path)
                raise ValueError(f"Missing content parameter: {file_upd}")

            Log.debug("Checking if allowed to edit file", path=path)
            if self.allowed_to_edit(path, content):
                edited.add(path)
                Log.debug("File marked for editing", path=path)

        Log.info("File update process completed", edited_count=len(edited), edited_files=edited)
        return edited
