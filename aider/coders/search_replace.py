#!/usr/bin/env python

import sys
from pathlib import Path

try:
    import git
except ImportError:
    git = None

from diff_match_patch import diff_match_patch
from tqdm import tqdm

from aider.dump import dump
from aider.utils import GitTemporaryDirectory
from treebeardhq import Log



class RelativeIndenter:
    """Rewrites text files to have relative indentation, which involves
    reformatting the leading white space on lines.  This format makes
    it easier to search and apply edits to pairs of code blocks which
    may differ significantly in their overall level of indentation.

    It removes leading white space which is shared with the preceding
    line.

    Original:
    ```
            Foo # indented 8
                Bar # indented 4 more than the previous line
                Baz # same indent as the previous line
                Fob # same indent as the previous line
    ```

    Becomes:
    ```
            Foo # indented 8
        Bar # indented 4 more than the previous line
    Baz # same indent as the previous line
    Fob # same indent as the previous line
    ```

    If the current line is *less* indented then the previous line,
    uses a unicode character to indicate outdenting.

    Original
    ```
            Foo
                Bar
                Baz
            Fob # indented 4 less than the previous line
    ```

    Becomes:
    ```
            Foo
        Bar
    Baz
    ←←←←Fob # indented 4 less than the previous line
    ```

    This is a similar original to the last one, but every line has
    been uniformly outdented:
    ```
    Foo
        Bar
        Baz
    Fob # indented 4 less than the previous line
    ```

    It becomes this result, which is very similar to the previous
    result.  Only the white space on the first line differs.  From the
    word Foo onwards, it is identical to the previous result.
    ```
    Foo
        Bar
    Baz
    ←←←←Fob # indented 4 less than the previous line
    ```

    """

    def __init__(self, texts):
        """
        Based on the texts, choose a unicode character that isn't in any of them.
        """
        Log.debug("Initializing RelativeIndenter", text_count=len(texts))
        chars = set()
        for text in texts:
            chars.update(text)

        ARROW = "←"
        if ARROW not in chars:
            self.marker = ARROW
            Log.debug("Using default arrow marker", marker=ARROW)
        else:
            self.marker = self.select_unique_marker(chars)
            Log.info("Using alternate marker due to collision", marker=self.marker)

    def select_unique_marker(self, chars):
        Log.debug("Searching for unique marker", chars_count=len(chars))
        for codepoint in range(0x10FFFF, 0x10000, -1):
            marker = chr(codepoint)
            if marker not in chars:
                Log.debug("Found unique marker", codepoint=codepoint, marker=marker)
                return marker

        Log.error("Failed to find unique marker character", chars_count=len(chars))
        raise ValueError("Could not find a unique marker")

    def make_relative(self, text):
        """
        Transform text to use relative indents.
        """
        Log.debug("Converting text to relative indentation", text_length=len(text))
        if self.marker in text:
            Log.error("Text already contains outdent marker", marker=self.marker)
            raise ValueError("Text already contains the outdent marker: {self.marker}")

        lines = text.splitlines(keepends=True)

        output = []
        prev_indent = ""
        for line in lines:
            line_without_end = line.rstrip("\n\r")

            len_indent = len(line_without_end) - len(line_without_end.lstrip())
            indent = line[:len_indent]
            change = len_indent - len(prev_indent)
            if change > 0:
                cur_indent = indent[-change:]
            elif change < 0:
                cur_indent = self.marker * -change
            else:
                cur_indent = ""

            out_line = cur_indent + "\n" + line[len_indent:]
            output.append(out_line)
            prev_indent = indent

        res = "".join(output)
        Log.info("Transformed text to relative indentation", 
                 input_lines=len(lines), 
                 output_lines=len(output), 
                 marker=self.marker)
        return res

    def make_absolute(self, text):
        """
        Transform text from relative back to absolute indents.
        """
        Log.debug("Converting text from relative to absolute indentation", text_length=len(text))
        lines = text.splitlines(keepends=True)

        output = []
        prev_indent = ""
        for i in range(0, len(lines), 2):
            dent = lines[i].rstrip("\r\n")
            non_indent = lines[i + 1]

            if dent.startswith(self.marker):
                len_outdent = len(dent)
                cur_indent = prev_indent[:-len_outdent]
                Log.debug("Applying outdent", outdent_length=len_outdent)
            else:
                cur_indent = prev_indent + dent
                Log.debug("Applying indent", indent_length=len(dent))

            if not non_indent.rstrip("\r\n"):
                out_line = non_indent  # don't indent a blank line
            else:
                out_line = cur_indent + non_indent

            output.append(out_line)
            prev_indent = cur_indent

        res = "".join(output)
        if self.marker in res:
            Log.error("Marker still present in text after transformation", marker=self.marker)
            raise ValueError("Error transforming text back to absolute indents")

        Log.info("Transformed text to absolute indentation", 
                 input_lines=len(lines), 
                 output_lines=len(output))
        return res


def map_patches(texts, patches, debug):
    search_text, replace_text, original_text = texts
    
    Log.debug("Starting patch mapping process", 
              search_len=len(search_text), 
              replace_len=len(replace_text), 
              original_len=len(original_text),
              patches_count=len(patches))

    dmp = diff_match_patch()
    dmp.Diff_Timeout = 5

    diff_s_o = dmp.diff_main(search_text, original_text)

    if debug:
        html = dmp.diff_prettyHtml(diff_s_o)
        Path("tmp.html").write_text(html)

        dump(len(search_text))
        dump(len(original_text))

    mapped_patches = []
    for patch in patches:
        start1 = patch.start1
        start2 = patch.start2

        patch.start1 = dmp.diff_xIndex(diff_s_o, start1)
        patch.start2 = dmp.diff_xIndex(diff_s_o, start2)
        mapped_patches.append(patch)

        if debug:
            print()
            print(start1, repr(search_text[start1 : start1 + 50]))
            print(patch.start1, repr(original_text[patch.start1 : patch.start1 + 50]))
            print(patch.diffs)
            print()
    
    Log.debug("Completed patch mapping", original_patches=len(patches), mapped_patches=len(mapped_patches))
    return mapped_patches


example = """Left
Left
    4 in
    4 in
        8 in
    4 in
Left
"""


def relative_indent(texts):
    ri = RelativeIndenter(texts)
    texts = list(map(ri.make_relative, texts))
    
    Log.debug("Converted texts to relative indentation", text_count=len(texts))
    return ri, texts


line_padding = 100


def line_pad(text):
    padding = "\n" * line_padding
    return padding + text + padding


def line_unpad(text):
    if set(text[:line_padding] + text[-line_padding:]) != set("\n"):
        return
    return text[line_padding:-line_padding]


def dmp_apply(texts, remap=True):
    debug = False
    # debug = True
    
    Log.info("Starting diff-match-patch apply operation", remap=remap)

    search_text, replace_text, original_text = texts

    dmp = diff_match_patch()
    dmp.Diff_Timeout = 5
    # dmp.Diff_EditCost = 16

    if remap:
        dmp.Match_Threshold = 0.95
        dmp.Match_Distance = 500
        dmp.Match_MaxBits = 128
        dmp.Patch_Margin = 32
    else:
        dmp.Match_Threshold = 0.5
        dmp.Match_Distance = 100_000
        dmp.Match_MaxBits = 32
        dmp.Patch_Margin = 8

    Log.debug("Calculating diff between search and replace text", 
              search_len=len(search_text), 
              replace_len=len(replace_text))
    diff = dmp.diff_main(search_text, replace_text, None)
    dmp.diff_cleanupSemantic(diff)
    dmp.diff_cleanupEfficiency(diff)

    Log.debug("Creating patches from diff")
    patches = dmp.patch_make(search_text, diff)

    if debug:
        html = dmp.diff_prettyHtml(diff)
        Path("tmp.search_replace_diff.html").write_text(html)

        for d in diff:
            print(d[0], repr(d[1]))

        for patch in patches:
            start1 = patch.start1
            print()
            print(start1, repr(search_text[start1 : start1 + 10]))
            print(start1, repr(replace_text[start1 : start1 + 10]))
            print(patch.diffs)

    if remap:
        Log.debug("Remapping patches to original text")
        patches = map_patches(texts, patches, debug)

    patches_text = dmp.patch_toText(patches)
    
    Log.debug("Applying patches to original text", patch_count=len(patches))
    new_text, success = dmp.patch_apply(patches, original_text)

    all_success = False not in success
    
    if debug:
        print(patches_text)
        dump(success)
        dump(all_success)

    if not all_success:
        Log.warn("Not all patches applied successfully", success=success)
        return

    Log.info("Successfully applied all patches", all_success=all_success)
    return new_text


def lines_to_chars(lines, mapping):
    new_text = []
    for char in lines:
        new_text.append(mapping[ord(char)])

    new_text = "".join(new_text)
    return new_text


def dmp_lines_apply(texts):
    debug = False
    # debug = True
    Log.debug("Beginning dmp_lines_apply", text_count=len(texts))

    for t in texts:
        assert t.endswith("\n"), t

    search_text, replace_text, original_text = texts
    Log.debug("Extracted texts", 
              search_text_length=len(search_text), 
              replace_text_length=len(replace_text), 
              original_text_length=len(original_text))

    dmp = diff_match_patch()
    dmp.Diff_Timeout = 5
    # dmp.Diff_EditCost = 16

    dmp.Match_Threshold = 0.1
    dmp.Match_Distance = 100_000
    dmp.Match_MaxBits = 32
    dmp.Patch_Margin = 1
    Log.debug("Configured diff_match_patch parameters", 
              match_threshold=dmp.Match_Threshold, 
              match_distance=dmp.Match_Distance)

    all_text = search_text + replace_text + original_text
    all_lines, _, mapping = dmp.diff_linesToChars(all_text, "")
    Log.debug("Converted lines to chars", mapping_length=len(mapping))
    assert len(all_lines) == len(all_text.splitlines())

    search_num = len(search_text.splitlines())
    replace_num = len(replace_text.splitlines())
    original_num = len(original_text.splitlines())
    Log.debug("Determined line counts", 
              search_lines=search_num, 
              replace_lines=replace_num, 
              original_lines=original_num)

    search_lines = all_lines[:search_num]
    replace_lines = all_lines[search_num : search_num + replace_num]
    original_lines = all_lines[search_num + replace_num :]

    assert len(search_lines) == search_num
    assert len(replace_lines) == replace_num
    assert len(original_lines) == original_num

    diff_lines = dmp.diff_main(search_lines, replace_lines, None)
    dmp.diff_cleanupSemantic(diff_lines)
    dmp.diff_cleanupEfficiency(diff_lines)
    Log.debug("Computed and cleaned up diff lines", diff_length=len(diff_lines))

    patches = dmp.patch_make(search_lines, diff_lines)
    Log.debug("Created patches", patch_count=len(patches))

    if debug:
        diff = list(diff_lines)
        dmp.diff_charsToLines(diff, mapping)
        # dump(diff)
        html = dmp.diff_prettyHtml(diff)
        Path("tmp.search_replace_diff.html").write_text(html)

        for d in diff:
            print(d[0], repr(d[1]))

    new_lines, success = dmp.patch_apply(patches, original_lines)
    Log.debug("Applied patches", success_count=sum(success), total_patches=len(success))
    new_text = lines_to_chars(new_lines, mapping)

    all_success = False not in success

    if debug:
        # print(new_text)
        dump(success)
        dump(all_success)

        # print(new_text)

    if not all_success:
        Log.warn("Not all patches applied successfully")
        return

    Log.info("Successfully applied all patches", 
             new_text_length=len(new_text), 
             all_applied=all_success)
    return new_text


def diff_lines(search_text, replace_text):
    Log.debug("Starting diff_lines calculation")
    dmp = diff_match_patch()
    dmp.Diff_Timeout = 5
    # dmp.Diff_EditCost = 16
    search_lines, replace_lines, mapping = dmp.diff_linesToChars(search_text, replace_text)
    Log.debug("Converted text to line-based representation", 
              search_lines_length=len(search_lines), 
              replace_lines_length=len(replace_lines))

    diff_lines = dmp.diff_main(search_lines, replace_lines, None)
    dmp.diff_cleanupSemantic(diff_lines)
    dmp.diff_cleanupEfficiency(diff_lines)
    Log.debug("Calculated and cleaned up diff lines", diff_count=len(diff_lines))

    diff = list(diff_lines)
    dmp.diff_charsToLines(diff, mapping)
    # dump(diff)

    udiff = []
    for d, lines in diff:
        if d < 0:
            d = "-"
        elif d > 0:
            d = "+"
        else:
            d = " "
        for line in lines.splitlines(keepends=True):
            udiff.append(d + line)
    
    Log.info("Generated unified diff", diff_lines_count=len(udiff))
    return udiff


def search_and_replace(texts):
    Log.debug("Starting search_and_replace")
    search_text, replace_text, original_text = texts

    num = original_text.count(search_text)
    # if num > 1:
    #    raise SearchTextNotUnique()
    if num == 0:
        Log.warn("Search text not found in original text")
        return

    Log.debug("Found search text in original", occurrences=num)
    new_text = original_text.replace(search_text, replace_text)
    Log.info("Completed search_and_replace", 
             original_length=len(original_text), 
             new_length=len(new_text))
    return new_text


def git_cherry_pick_osr_onto_o(texts):
    Log.debug("Starting git_cherry_pick_osr_onto_o")
    search_text, replace_text, original_text = texts

    with GitTemporaryDirectory() as dname:
        try:
            repo = git.Repo(dname)
            Log.debug("Created git repository", repo_dir=dname)

            fname = Path(dname) / "file.txt"

            # Make O->S->R
            fname.write_text(original_text)
            repo.git.add(str(fname))
            repo.git.commit("-m", "original")
            original_hash = repo.head.commit.hexsha
            Log.debug("Committed original text", hash=original_hash)

            fname.write_text(search_text)
            repo.git.add(str(fname))
            repo.git.commit("-m", "search")
            search_hash = repo.head.commit.hexsha
            Log.debug("Committed search text", hash=search_hash)

            fname.write_text(replace_text)
            repo.git.add(str(fname))
            repo.git.commit("-m", "replace")
            replace_hash = repo.head.commit.hexsha
            Log.debug("Committed replace text", hash=replace_hash)

            # go back to O
            repo.git.checkout(original_hash)
            Log.debug("Checked out original commit")

            # cherry pick R onto original
            try:
                repo.git.cherry_pick(replace_hash, "--minimal")
                Log.debug("Successfully cherry-picked replace onto original")
            except (git.exc.ODBError, git.exc.GitError) as e:
                Log.warn("Cherry pick failed due to merge conflicts", error=e)
                return

            new_text = fname.read_text()
            Log.info("Completed git cherry pick", 
                     original_hash=original_hash, 
                     replace_hash=replace_hash, 
                     new_text_length=len(new_text))
            return new_text
        except Exception as e:
            Log.error("Unexpected error in git operations", error=e)
            raise


def git_cherry_pick_sr_onto_so(texts):
    Log.debug("Starting git_cherry_pick_sr_onto_so")
    search_text, replace_text, original_text = texts

    with GitTemporaryDirectory() as dname:
        try:
            repo = git.Repo(dname)
            Log.debug("Created git repository", repo_dir=dname)

            fname = Path(dname) / "file.txt"

            fname.write_text(search_text)
            repo.git.add(str(fname))
            repo.git.commit("-m", "search")
            search_hash = repo.head.commit.hexsha
            Log.debug("Committed search text", hash=search_hash)

            # make search->replace
            fname.write_text(replace_text)
            repo.git.add(str(fname))
            repo.git.commit("-m", "replace")
            replace_hash = repo.head.commit.hexsha
            Log.debug("Committed replace text", hash=replace_hash)

            # go back to search,
            repo.git.checkout(search_hash)
            Log.debug("Checked out search commit")

            # make search->original
            fname.write_text(original_text)
            repo.git.add(str(fname))
            repo.git.commit("-m", "original")
            original_hash = repo.head.commit.hexsha
            Log.debug("Committed original text on search branch", hash=original_hash)

            # cherry pick replace onto original
            try:
                repo.git.cherry_pick(replace_hash, "--minimal")
                Log.debug("Successfully cherry-picked replace onto original")
            except (git.exc.ODBError, git.exc.GitError) as e:
                Log.warn("Cherry pick failed due to merge conflicts", error=e)
                return

            new_text = fname.read_text()
            Log.info("Completed git cherry pick", 
                     search_hash=search_hash, 
                     replace_hash=replace_hash, 
                     original_hash=original_hash, 
                     new_text_length=len(new_text))
            return new_text
        except Exception as e:
            Log.error("Unexpected error in git operations", error=e)
            raise


class SearchTextNotUnique(ValueError):
    pass


all_preprocs = [
    # (strip_blank_lines, relative_indent, reverse_lines)
    (False, False, False),
    (True, False, False),
    (False, True, False),
    (True, True, False),
    # (False, False, True),
    # (True, False, True),
    # (False, True, True),
    # (True, True, True),
]

always_relative_indent = [
    (False, True, False),
    (True, True, False),
    # (False, True, True),
    # (True, True, True),
]

editblock_strategies = [
    (search_and_replace, all_preprocs),
    (git_cherry_pick_osr_onto_o, all_preprocs),
    (dmp_lines_apply, all_preprocs),
]

never_relative = [
    (False, False),
    (True, False),
]

udiff_strategies = [
    (search_and_replace, all_preprocs),
    (git_cherry_pick_osr_onto_o, all_preprocs),
    (dmp_lines_apply, all_preprocs),
]


def flexible_search_and_replace(texts, strategies):
    """Try a series of search/replace methods, starting from the most
    literal interpretation of search_text. If needed, progress to more
    flexible methods, which can accommodate divergence between
    search_text and original_text and yet still achieve the desired
    edits.
    """
    Log.info("Starting flexible search and replace", text_length=len(texts[0]))

    for strategy, preprocs in strategies:
        for preproc in preprocs:
            Log.debug("Attempting strategy", strategy=strategy.__name__, preproc=preproc)
            res = try_strategy(texts, strategy, preproc)
            if res:
                Log.info("Found successful strategy", strategy=strategy.__name__, preproc=preproc)
                return res
    
    Log.warn("No successful strategy found for search and replace")
    return None


def reverse_lines(text):
    lines = text.splitlines(keepends=True)
    lines.reverse()
    return "".join(lines)


def try_strategy(texts, strategy, preproc):
    preproc_strip_blank_lines, preproc_relative_indent, preproc_reverse = preproc
    ri = None

    Log.debug("Preprocessing text", strip_blank_lines=preproc_strip_blank_lines, 
              relative_indent=preproc_relative_indent, reverse=preproc_reverse)

    if preproc_strip_blank_lines:
        texts = strip_blank_lines(texts)
    if preproc_relative_indent:
        ri, texts = relative_indent(texts)
    if preproc_reverse:
        texts = list(map(reverse_lines, texts))

    Log.debug("Executing strategy", strategy=strategy.__name__)
    res = strategy(texts)

    if res and preproc_reverse:
        Log.debug("Reversing result lines")
        res = reverse_lines(res)

    if res and preproc_relative_indent:
        try:
            Log.debug("Converting relative indentation to absolute")
            res = ri.make_absolute(res)
        except ValueError as e:
            Log.error("Failed to make absolute indentation", error=e)
            return

    return res


def strip_blank_lines(texts):
    # strip leading and trailing blank lines
    texts = [text.strip("\n") + "\n" for text in texts]
    return texts


def read_text(fname):
    text = Path(fname).read_text()
    return text


def proc(dname):
    dname = Path(dname)
    Log.info("Processing directory", directory=str(dname))

    try:
        search_text = read_text(dname / "search")
        replace_text = read_text(dname / "replace")
        original_text = read_text(dname / "original")
    except FileNotFoundError as e:
        Log.error("Required files not found", error=e, directory=str(dname))
        return

    ####

    texts = search_text, replace_text, original_text
    Log.debug("Loaded text files", 
              search_length=len(search_text), 
              replace_length=len(replace_text), 
              original_length=len(original_text))

    strategies = [
        # (search_and_replace, all_preprocs),
        # (git_cherry_pick_osr_onto_o, all_preprocs),
        # (git_cherry_pick_sr_onto_so, all_preprocs),
        # (dmp_apply, all_preprocs),
        (dmp_lines_apply, all_preprocs),
    ]

    short_names = dict(
        search_and_replace="sr",
        git_cherry_pick_osr_onto_o="cp_o",
        git_cherry_pick_sr_onto_so="cp_so",
        dmp_apply="dmp",
        dmp_lines_apply="dmpl",
    )

    patched = dict()
    for strategy, preprocs in strategies:
        for preproc in preprocs:
            method = strategy.__name__
            method = short_names[method]

            strip_blank, rel_indent, rev_lines = preproc
            if strip_blank or rel_indent:
                method += "_"
            if strip_blank:
                method += "s"
            if rel_indent:
                method += "i"
            if rev_lines:
                method += "r"

            Log.debug("Trying strategy with preprocessing", 
                      method=method, 
                      strategy=strategy.__name__, 
                      strip_blank=strip_blank, 
                      rel_indent=rel_indent, 
                      rev_lines=rev_lines)
            
            res = try_strategy(texts, strategy, preproc)
            patched[method] = res
            
            if res:
                Log.debug("Strategy produced a result", method=method, result_length=len(res))
            else:
                Log.debug("Strategy failed to produce a result", method=method)

    results = []
    for method, res in patched.items():
        out_fname = dname / f"original.{method}"
        if out_fname.exists():
            out_fname.unlink()

        if res:
            out_fname.write_text(res)

            correct = (dname / "correct").read_text()
            if res == correct:
                res = "pass"
                Log.info("Method produced correct result", method=method, directory=str(dname))
            else:
                res = "WRONG"
                Log.warn("Method produced incorrect result", method=method, directory=str(dname))
        else:
            res = "fail"
            Log.debug("Method failed to produce a result", method=method, directory=str(dname))

        results.append((method, res))

    Log.info("Processing complete", directory=str(dname), num_results=len(results))
    return results


def colorize_result(result):
    colors = {
        "pass": "\033[102;30mpass\033[0m",  # Green background, black text
        "WRONG": "\033[101;30mWRONG\033[0m",  # Red background, black text
        "fail": "\033[103;30mfail\033[0m",  # Yellow background, black text
    }
    return colors.get(result, result)  # Default to original result if not found


def main(dnames):
    Log.info("Starting processing of directories", count=len(dnames))
    all_results = []
    for dname in tqdm(dnames):
        dname = Path(dname)
        Log.debug("Processing directory", directory=str(dname))
        results = proc(dname)
        for method, res in results:
            all_results.append((dname, method, res))
            # print(dname, method, colorize_result(res))
    
    Log.debug("Collected all results", result_count=len(all_results))

    # Create a 2D table with directories along the right and methods along the top
    # Collect all unique methods and directories
    methods = []
    for _, method, _ in all_results:
        if method not in methods:
            methods.append(method)
    
    Log.debug("Identified unique methods", methods=methods, count=len(methods))
    directories = dnames

    # Sort directories by decreasing number of 'pass' results
    pass_counts = {
        dname: sum(
            res == "pass" for dname_result, _, res in all_results if str(dname) == str(dname_result)
        )
        for dname in directories
    }
    Log.debug("Calculated pass counts for directories", pass_counts=pass_counts)
    directories.sort(key=lambda dname: pass_counts[dname], reverse=True)

    # Create a results matrix
    results_matrix = {dname: {method: "" for method in methods} for dname in directories}

    # Populate the results matrix
    for dname, method, res in all_results:
        results_matrix[str(dname)][method] = res
    
    Log.debug("Results matrix created", matrix_size=f"{len(directories)}x{len(methods)}")

    # Print the 2D table
    # Print the header
    print("{:<20}".format("Directory"), end="")
    for method in methods:
        print("{:<9}".format(method), end="")
    print()

    # Print the rows with colorized results
    for dname in directories:
        print("{:<20}".format(Path(dname).name), end="")
        for method in methods:
            res = results_matrix[dname][method]
            colorized_res = colorize_result(res)
            res_l = 9 + len(colorized_res) - len(res)
            fmt = "{:<" + str(res_l) + "}"
            print(fmt.format(colorized_res), end="")
        print()
    
    Log.info("Completed results table generation", directory_count=len(directories), method_count=len(methods))


if __name__ == "__main__":
    Log.info("Starting main execution", args=sys.argv[1:])
    status = main(sys.argv[1:])
    Log.info("Execution completed", status=status)
    sys.exit(status)
