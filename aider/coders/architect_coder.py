from .architect_prompts import ArchitectPrompts
from .ask_coder import AskCoder
from .base_coder import Coder
from treebeardhq import Log



class ArchitectCoder(AskCoder):
    edit_format = "architect"
    gpt_prompts = ArchitectPrompts()
    auto_accept_architect = False

    def reply_completed(self):
        content = self.partial_response_content
        Log.debug("Processing architect reply", content_empty=not content or not content.strip())

        if not content or not content.strip():
            return

        if not self.auto_accept_architect and not self.io.confirm_ask("Edit the files?"):
            Log.info("User declined architecture changes", auto_accept=self.auto_accept_architect)
            return

        kwargs = dict()

        # Use the editor_model from the main_model if it exists, otherwise use the main_model itself
        editor_model = self.main_model.editor_model or self.main_model
        Log.debug("Selected editor model", editor_model=editor_model, using_main_model=self.main_model.editor_model is None)

        kwargs["main_model"] = editor_model
        kwargs["edit_format"] = self.main_model.editor_edit_format
        kwargs["suggest_shell_commands"] = False
        kwargs["map_tokens"] = 0
        kwargs["total_cost"] = self.total_cost
        kwargs["cache_prompts"] = False
        kwargs["num_cache_warming_pings"] = 0
        kwargs["summarize_from_coder"] = False

        new_kwargs = dict(io=self.io, from_coder=self)
        new_kwargs.update(kwargs)

        Log.debug("Creating editor coder instance", kwargs=kwargs)
        editor_coder = Coder.create(**new_kwargs)
        editor_coder.cur_messages = []
        editor_coder.done_messages = []

        if self.verbose:
            editor_coder.show_announcements()

        Log.info("Running editor with architect content", verbose=self.verbose)
        editor_coder.run(with_message=content, preproc=False)

        self.move_back_cur_messages("I made those changes to the files.")
        self.total_cost = editor_coder.total_cost
        self.aider_commit_hashes = editor_coder.aider_commit_hashes
        Log.info("Completed architect code editing", total_cost=self.total_cost, has_commits=bool(self.aider_commit_hashes))
