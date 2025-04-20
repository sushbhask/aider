import difflib
from itertools import groupby
from pathlib import Path

from ..dump import dump  # noqa: F401
from .base_coder import Coder
from .search_replace import (
    SearchTextNotUnique,
    all_preprocs,
    diff_lines,
    flexible_search_and_replace,
    search_and_replace,
)
from .udiff_prompts import UnifiedDiffPrompts
from treebeardhq import Log


no_match_error = """UnifiedDiffNoMatch: hunk failed to apply!

{path} does not contain lines that match the diff you provided!
Try again.
DO NOT skip blank lines, comments, docstrings, etc!
The diff needs to apply cleanly to the lines in {path}!

{path} does not contain these {num_lines} exact lines in a row:
```
{original}```
"""


not_unique_error = """UnifiedDiffNotUnique: hunk failed to apply!

{path} contains multiple sets of lines that match the diff you provided!
Try again.
Use additional ` ` lines to provide context that uniquely indicates which code needs to be changed.
The diff needs to apply to a unique set of lines in {path}!

{path} contains multiple copies of these {num_lines} lines:
```
{original}```
"""

other_hunks_applied = (
    "Note: some hunks did apply successfully. See the updated source code shown above.\n\n"
)


class UnifiedDiffCoder(Coder):
    """A coder that uses unified diff format for code modifications."""

    edit_format = "udiff"
    gpt_prompts = UnifiedDiffPrompts()

    def get_edits(self):
        content = self.partial_response_content
        
        Log.debug("Extracting diffs from content", content_length=len(content))
        # might raise ValueError for malformed ORIG/UPD blocks
        raw_edits = list(find_diffs(content))
        Log.debug("Found raw edits", count=len(raw_edits))

        last_path = None
        edits = []
        for path, hunk in raw_edits:
            if path:
                last_path = path
            else:
                path = last_path
            edits.append((path, hunk))
        
        Log.info("Extracted edits from diff content", edit_count=len(edits))
        return edits

    def apply_edits(self, edits):
        Log.debug("Starting to apply edits", edit_count=len(edits))
        seen = set()
        uniq = []
        for path, hunk in edits:
            hunk = normalize_hunk(hunk)
            if not hunk:
                continue

            this = [path + "\n"] + hunk
            this = "".join(this)

            if this in seen:
                continue
            seen.add(this)

            uniq.append((path, hunk))
        
        Log.debug("Filtered to unique edits", unique_edit_count=len(uniq), original_count=len(edits))

        errors = []
        for path, hunk in uniq:
            Log.debug("Applying edit to file", path=path)
            full_path = self.abs_root_path(path)
            content = self.io.read_text(full_path)

            original, _ = hunk_to_before_after(hunk)

            try:
                content = do_replace(full_path, content, hunk)
            except SearchTextNotUnique:
                Log.warn("Search text not unique in file", path=path, hunk_lines=len(hunk))
                errors.append(
                    not_unique_error.format(
                        path=path, original=original, num_lines=len(original.splitlines())
                    )
                )
                continue

            if not content:
                Log.warn("No match found for hunk in file", path=path, hunk_lines=len(hunk))
                errors.append(
                    no_match_error.format(
                        path=path, original=original, num_lines=len(original.splitlines())
                    )
                )
                continue

            # SUCCESS!
            Log.info("Successfully applied edit to file", path=path)
            self.io.write_text(full_path, content)

        if errors:
            errors = "\n\n".join(errors)
            if len(errors) < len(uniq):
                errors += other_hunks_applied
            Log.error("Encountered errors while applying edits", error_count=len(errors))
            raise ValueError(errors)
        
        Log.info("Successfully applied all edits", edit_count=len(uniq))


def do_replace(fname, content, hunk):
    fname = Path(fname)
    
    Log.debug("Attempting to replace content in file", fname=str(fname), hunk_lines=len(hunk))
    before_text, after_text = hunk_to_before_after(hunk)

    # does it want to make a new file?
    if not fname.exists() and not before_text.strip():
        Log.info("Creating new file", fname=str(fname))
        fname.touch()
        content = ""

    if content is None:
        return

    # TODO: handle inserting into new file
    if not before_text.strip():
        # append to existing file, or start a new file
        Log.info("Appending content to file", fname=str(fname))
        new_content = content + after_text
        return new_content

    new_content = None

    new_content = apply_hunk(content, hunk)
    if new_content:
        Log.debug("Successfully applied hunk", fname=str(fname))
        return new_content
    
    Log.warn("Failed to apply hunk", fname=str(fname))


def collapse_repeats(s):
    return "".join(k for k, g in groupby(s))


def apply_hunk(content, hunk):
    Log.debug("Applying hunk to content", content_length=len(content), hunk_lines=len(hunk))
    before_text, after_text = hunk_to_before_after(hunk)

    res = directly_apply_hunk(content, hunk)
    if res:
        Log.debug("Direct hunk application succeeded")
        return res

    Log.debug("Direct application failed, making new lines explicit")
    hunk = make_new_lines_explicit(content, hunk)

    # just consider space vs not-space
    ops = "".join([line[0] for line in hunk])
    ops = ops.replace("-", "x")
    ops = ops.replace("+", "x")
    ops = ops.replace("\n", " ")

    cur_op = " "
    section = []
    sections = []

    for i in range(len(ops)):
        op = ops[i]
        if op != cur_op:
            sections.append(section)
            section = []
            cur_op = op
        section.append(hunk[i])

    sections.append(section)
    if cur_op != " ":
        sections.append([])
    
    Log.debug("Split hunk into sections", section_count=len(sections))

    all_done = True
    for i in range(2, len(sections), 2):
        preceding_context = sections[i - 2]
        changes = sections[i - 1]
        following_context = sections[i]

        Log.debug("Applying partial hunk", 
                 preceding_lines=len(preceding_context), 
                 change_lines=len(changes), 
                 following_lines=len(following_context))
        
        res = apply_partial_hunk(content, preceding_context, changes, following_context)
        if res:
            content = res
        else:
            all_done = False
            Log.warn("Failed to apply partial hunk", 
                    preceding_lines=len(preceding_context), 
                    change_lines=len(changes), 
                    following_lines=len(following_context))
            # FAILED!
            # this_hunk = preceding_context + changes + following_context
            break

    if all_done:
        Log.info("Successfully applied all hunk sections")
        return content


def flexi_just_search_and_replace(texts):
    strategies = [
        (search_and_replace, all_preprocs),
    ]
    
    Log.debug("Starting flexible search and replace", texts_length=len(texts))
    return flexible_search_and_replace(texts, strategies)


def make_new_lines_explicit(content, hunk):
    before, after = hunk_to_before_after(hunk)
    
    diff = diff_lines(before, content)
    
    back_diff = []
    for line in diff:
        if line[0] == "+":
            continue
        # if line[0] == "-":
        #    line = "+" + line[1:]
        
        back_diff.append(line)
    
    new_before = directly_apply_hunk(before, back_diff)
    if not new_before:
        Log.debug("Failed to get new_before content", content_length=len(content) if content else 0)
        return hunk
    
    if len(new_before.strip()) < 10:
        Log.debug("New before content too short", length=len(new_before.strip()))
        return hunk
    
    before = before.splitlines(keepends=True)
    new_before = new_before.splitlines(keepends=True)
    after = after.splitlines(keepends=True)
    
    if len(new_before) < len(before) * 0.66:
        Log.debug("New before content too small compared to original before", new_before_length=len(new_before), before_length=len(before))
        return hunk
    
    new_hunk = difflib.unified_diff(new_before, after, n=max(len(new_before), len(after)))
    new_hunk = list(new_hunk)[3:]
    
    Log.debug("Generated new hunk with explicit new lines", new_hunk_length=len(new_hunk))
    return new_hunk


def cleanup_pure_whitespace_lines(lines):
    res = [
        line if line.strip() else line[-(len(line) - len(line.rstrip("\r\n")))] for line in lines
    ]
    return res


def normalize_hunk(hunk):
    before, after = hunk_to_before_after(hunk, lines=True)
    
    before = cleanup_pure_whitespace_lines(before)
    after = cleanup_pure_whitespace_lines(after)
    
    diff = difflib.unified_diff(before, after, n=max(len(before), len(after)))
    diff = list(diff)[3:]
    Log.debug("Normalized hunk", diff_length=len(diff))
    return diff


def directly_apply_hunk(content, hunk):
    before, after = hunk_to_before_after(hunk)
    
    if not before:
        return
    
    before_lines, _ = hunk_to_before_after(hunk, lines=True)
    before_lines = "".join([line.strip() for line in before_lines])
    
    # Refuse to do a repeated search and replace on a tiny bit of non-whitespace context
    if len(before_lines) < 10 and content.count(before) > 1:
        Log.debug("Refusing to apply hunk with small context that appears multiple times", before_length=len(before_lines), occurrences=content.count(before))
        return
    
    try:
        new_content = flexi_just_search_and_replace([before, after, content])
        Log.debug("Successfully applied hunk directly", content_changed=(new_content != content))
    except SearchTextNotUnique:
        Log.warn("Search text not unique when directly applying hunk", before_length=len(before))
        new_content = None
    
    return new_content


def apply_partial_hunk(content, preceding_context, changes, following_context):
    len_prec = len(preceding_context)
    len_foll = len(following_context)
    
    use_all = len_prec + len_foll
    
    Log.debug("Attempting to apply partial hunk", preceding_context_length=len_prec, changes_length=len(changes), following_context_length=len_foll)
    
    # if there is a - in the hunk, we can go all the way to `use=0`
    for drop in range(use_all + 1):
        use = use_all - drop
        
        for use_prec in range(len_prec, -1, -1):
            if use_prec > use:
                continue
            
            use_foll = use - use_prec
            if use_foll > len_foll:
                continue
            
            if use_prec:
                this_prec = preceding_context[-use_prec:]
            else:
                this_prec = []
            
            this_foll = following_context[:use_foll]
            
            res = directly_apply_hunk(content, this_prec + changes + this_foll)
            if res:
                Log.info("Successfully applied partial hunk", use_prec=use_prec, use_foll=use_foll)
                return res
    
    Log.debug("Failed to apply partial hunk with any context combination")


def find_diffs(content):
    # We can always fence with triple-quotes, because all the udiff content
    # is prefixed with +/-/space.
    
    if not content.endswith("\n"):
        content = content + "\n"
    
    lines = content.splitlines(keepends=True)
    line_num = 0
    edits = []
    
    Log.debug("Finding diffs in content", lines_count=len(lines))
    
    while line_num < len(lines):
        while line_num < len(lines):
            line = lines[line_num]
            if line.startswith("```diff"):
                line_num, these_edits = process_fenced_block(lines, line_num + 1)
                edits += these_edits
                Log.debug("Found code block diff", edits_found=len(these_edits))
                break
            line_num += 1
    
    # For now, just take 1!
    # edits = edits[:1]
    
    Log.info("Total diffs found", count=len(edits))
    return edits


def process_fenced_block(lines, start_line_num):
    Log.debug("Processing fenced block", start_line=start_line_num, total_lines=len(lines))
    for line_num in range(start_line_num, len(lines)):
        line = lines[line_num]
        if line.startswith("```"):
            break

    block = lines[start_line_num:line_num]
    block.append("@@ @@")
    Log.debug("Extracted block content", block_size=len(block))

    if block[0].startswith("--- ") and block[1].startswith("+++ "):
        # Extract the file path, considering that it might contain spaces
        a_fname = block[0][4:].strip()
        b_fname = block[1][4:].strip()

        # Check if standard git diff prefixes are present and strip them
        if a_fname.startswith("a/") and b_fname.startswith("b/"):
            fname = b_fname[2:]
        else:
            # Otherwise, assume the path is as intended
            fname = b_fname

        block = block[2:]
        Log.debug("Found filename in diff header", filename=fname, a_filename=a_fname, b_filename=b_fname)
    else:
        fname = None
        Log.debug("No filename found in block")

    edits = []

    keeper = False
    hunk = []
    op = " "
    for line in block:
        hunk.append(line)
        if len(line) < 2:
            continue

        if line.startswith("+++ ") and hunk[-2].startswith("--- "):
            if hunk[-3] == "\n":
                hunk = hunk[:-3]
            else:
                hunk = hunk[:-2]

            edits.append((fname, hunk))
            Log.debug("Found new file in hunk", filename=fname, hunk_size=len(hunk))
            hunk = []
            keeper = False

            fname = line[4:].strip()
            continue

        op = line[0]
        if op in "-+":
            keeper = True
            continue
        if op != "@":
            continue
        if not keeper:
            hunk = []
            continue

        hunk = hunk[:-1]
        edits.append((fname, hunk))
        Log.debug("Extracted edit hunk", filename=fname, hunk_size=len(hunk))
        hunk = []
        keeper = False

    Log.info("Completed processing fenced block", edits_count=len(edits), end_line=line_num+1)
    return line_num + 1, edits


def hunk_to_before_after(hunk, lines=False):
    Log.debug("Converting hunk to before/after", hunk_size=len(hunk), return_lines=lines)
    before = []
    after = []
    op = " "
    for line in hunk:
        if len(line) < 2:
            op = " "
            line = line
        else:
            op = line[0]
            line = line[1:]

        if op == " ":
            before.append(line)
            after.append(line)
        elif op == "-":
            before.append(line)
        elif op == "+":
            after.append(line)

    if lines:
        Log.debug("Returning before/after as lines", before_count=len(before), after_count=len(after))
        return before, after

    before = "".join(before)
    after = "".join(after)
    
    Log.debug("Returning before/after as text", before_length=len(before), after_length=len(after))
    return before, after
