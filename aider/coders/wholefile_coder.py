from pathlib import Path

from aider import diffs

from ..dump import dump  # noqa: F401
from .base_coder import Coder
from .wholefile_prompts import WholeFilePrompts
from treebeardhq import Log



class WholeFileCoder(Coder):
    """A coder that operates on entire files for code modifications."""

    edit_format = "whole"
    gpt_prompts = WholeFilePrompts()

    def render_incremental_response(self, final):
        try:
            return self.get_edits(mode="diff")
        except ValueError:
            Log.debug("Failed to get edits in diff mode, falling back to multi response content", final=final)
            return self.get_multi_response_content_in_progress()

    def get_edits(self, mode="update"):
        Log.debug("Starting to get edits", mode=mode)
        content = self.get_multi_response_content_in_progress()

        chat_files = self.get_inchat_relative_files()
        Log.debug("Retrieved chat files", file_count=len(chat_files), files=chat_files)

        output = []
        lines = content.splitlines(keepends=True)

        edits = []

        saw_fname = None
        fname = None
        fname_source = None
        new_lines = []
        for i, line in enumerate(lines):
            if line.startswith(self.fence[0]) or line.startswith(self.fence[1]):
                if fname is not None:
                    # ending an existing block
                    saw_fname = None

                    full_path = self.abs_root_path(fname)
                    Log.debug("Ending code block", fname=fname, fname_source=fname_source, line_count=len(new_lines))

                    if mode == "diff":
                        output += self.do_live_diff(full_path, new_lines, True)
                    else:
                        edits.append((fname, fname_source, new_lines))

                    fname = None
                    fname_source = None
                    new_lines = []
                    continue

                # fname==None ... starting a new block
                if i > 0:
                    fname_source = "block"
                    fname = lines[i - 1].strip()
                    fname = fname.strip("*")  # handle **filename.py**
                    fname = fname.rstrip(":")
                    fname = fname.strip("`")
                    fname = fname.lstrip("#")
                    fname = fname.strip()

                    # Issue #1232
                    if len(fname) > 250:
                        Log.warn("Filename exceeds maximum length", length=len(fname))
                        fname = ""

                    # Did gpt prepend a bogus dir? It especially likes to
                    # include the path/to prefix from the one-shot example in
                    # the prompt.
                    if fname and fname not in chat_files and Path(fname).name in chat_files:
                        Log.debug("Corrected filename path", original=fname, corrected=Path(fname).name)
                        fname = Path(fname).name
                if not fname:  # blank line? or ``` was on first line i==0
                    if saw_fname:
                        fname = saw_fname
                        fname_source = "saw"
                    elif len(chat_files) == 1:
                        fname = chat_files[0]
                        fname_source = "chat"
                    else:
                        # TODO: sense which file it is by diff size
                        Log.error("Missing filename before code block", fence=self.fence[0])
                        raise ValueError(
                            f"No filename provided before {self.fence[0]} in file listing"
                        )
                
                Log.debug("Starting new code block", fname=fname, fname_source=fname_source)

            elif fname is not None:
                new_lines.append(line)
            else:
                for word in line.strip().split():
                    word = word.rstrip(".:,;!")
                    for chat_file in chat_files:
                        quoted_chat_file = f"`{chat_file}`"
                        if word == quoted_chat_file:
                            saw_fname = chat_file
                            Log.debug("Found filename reference in text", fname=chat_file)

                output.append(line)

        if mode == "diff":
            if fname is not None:
                # ending an existing block
                full_path = (Path(self.root) / fname).absolute()
                Log.debug("Processing final code block for diff", fname=fname, line_count=len(new_lines))
                output += self.do_live_diff(full_path, new_lines, False)
            return "\n".join(output)

        if fname:
            Log.debug("Adding final edit", fname=fname, fname_source=fname_source, line_count=len(new_lines))
            edits.append((fname, fname_source, new_lines))

        seen = set()
        refined_edits = []
        # process from most reliable filename, to least reliable
        for source in ("block", "saw", "chat"):
            for fname, fname_source, new_lines in edits:
                if fname_source != source:
                    continue
                # if a higher priority source already edited the file, skip
                if fname in seen:
                    continue

                seen.add(fname)
                refined_edits.append((fname, fname_source, new_lines))

        Log.info("Completed edit processing", mode=mode, edit_count=len(refined_edits), sources=[e[1] for e in refined_edits])
        return refined_edits

    def apply_edits(self, edits):
        for path, fname_source, new_lines in edits:
            full_path = self.abs_root_path(path)
            new_lines = "".join(new_lines)
            Log.info("Writing edits to file", path=path, source=fname_source, length=len(new_lines))
            self.io.write_text(full_path, new_lines)

    def do_live_diff(self, full_path, new_lines, final):
        if Path(full_path).exists():
            orig_lines = self.io.read_text(full_path)
            if orig_lines is not None:
                orig_lines = orig_lines.splitlines(keepends=True)
                Log.debug("Generating diff", path=full_path, original_lines=len(orig_lines), new_lines=len(new_lines), final=final)

                show_diff = diffs.diff_partial_update(
                    orig_lines,
                    new_lines,
                    final=final,
                ).splitlines()
                return show_diff

        Log.debug("No existing file to diff against, returning raw content", path=full_path)
        output = ["```"] + new_lines + ["```"]
        return output
