from ..dump import dump  # noqa: F401
from .base_coder import Coder
from .help_prompts import HelpPrompts
from treebeardhq import Log



class HelpCoder(Coder):
    """Interactive help and documentation about aider."""
    edit_format = "help"
    gpt_prompts = HelpPrompts()

    def get_edits(self, mode="update"):
        Log.debug("Getting help edits", mode=mode)
        return []

    def apply_edits(self, edits):
        Log.debug("Applying help edits", edits_count=len(edits) if edits else 0)
        pass
