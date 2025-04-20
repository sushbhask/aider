from .base_coder import Coder
from .context_prompts import ContextPrompts
from treebeardhq import Log



class ContextCoder(Coder):
    """Identify which files need to be edited for a given request."""

    edit_format = "context"
    gpt_prompts = ContextPrompts()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.repo_map:
            return

        self.repo_map.refresh = "always"
        self.repo_map.max_map_tokens *= self.repo_map.map_mul_no_files
        self.repo_map.map_mul_no_files = 1.0

    def reply_completed(self):
        content = self.partial_response_content
        if not content or not content.strip():
            Log.debug("Response content is empty", content=content)
            return True

        # dump(repr(content))
        current_rel_fnames = set(self.get_inchat_relative_files())
        mentioned_rel_fnames = set(self.get_file_mentions(content, ignore_current=True))

        # dump(current_rel_fnames)
        # dump(mentioned_rel_fnames)
        # dump(current_rel_fnames == mentioned_rel_fnames)

        if mentioned_rel_fnames == current_rel_fnames:
            Log.debug("Mentioned filenames match current filenames", 
                     current_files=current_rel_fnames, 
                     mentioned_files=mentioned_rel_fnames)
            return True

        if self.num_reflections >= self.max_reflections - 1:
            Log.info("Maximum reflections reached", 
                    num_reflections=self.num_reflections, 
                    max_reflections=self.max_reflections)
            return True

        self.abs_fnames = set()
        for fname in mentioned_rel_fnames:
            self.add_rel_fname(fname)
        # dump(self.get_inchat_relative_files())
        
        Log.info("Adding newly mentioned files to context", 
                mentioned_files=mentioned_rel_fnames, 
                current_files=current_rel_fnames,
                new_files=mentioned_rel_fnames - current_rel_fnames)

        self.reflected_message = self.gpt_prompts.try_again

        # mentioned_idents = self.get_ident_mentions(cur_msg_text)
        # if mentioned_idents:

        return True

    def check_for_file_mentions(self, content):
        pass
