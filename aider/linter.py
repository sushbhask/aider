import os
import re
import subprocess
import sys
import traceback
import warnings
import shlex
from dataclasses import dataclass
from pathlib import Path

from grep_ast import TreeContext, filename_to_lang
from grep_ast.tsl import get_parser  # noqa: E402

from aider.dump import dump  # noqa: F401
from aider.run_cmd import run_cmd_subprocess  # noqa: F401
from treebeardhq import Log

# tree_sitter is throwing a FutureWarning
# tree_sitter is throwing a FutureWarning
warnings.simplefilter("ignore", category=FutureWarning)


class Linter:
    def __init__(self, encoding="utf-8", root=None):
        self.encoding = encoding
        self.root = root

        self.languages = dict(
            python=self.py_lint,
        )
        self.all_lint_cmd = None

    def set_linter(self, lang, cmd):
        if lang:
            self.languages[lang] = cmd
            return

        self.all_lint_cmd = cmd

    def get_rel_fname(self, fname):
        if self.root:
            try:
                return os.path.relpath(fname, self.root)
            except ValueError:
                Log.debug("Could not get relative path", fname=fname, error=ValueError)
                return fname
        else:
            return fname

    def run_cmd(self, cmd, rel_fname, code):
        cmd += " " + shlex.quote(rel_fname)
        
        Log.debug("Executing lint command", cmd=cmd, file=rel_fname)
        returncode = 0
        stdout = ""
        try:
            returncode, stdout = run_cmd_subprocess(
                cmd,
                cwd=self.root,
                encoding=self.encoding,
            )
        except OSError as err:
            Log.error("Unable to execute lint command", error=err, cmd=cmd)
            print(f"Unable to execute lint command: {err}")
            return
        errors = stdout
        if returncode == 0:
            Log.debug("Lint command completed successfully", file=rel_fname)
            return  # zero exit status

        res = f"## Running: {cmd}\n\n"
        res += errors
        
        Log.info("Lint command found errors", file=rel_fname, returncode=returncode)
        return self.errors_to_lint_result(rel_fname, res)

    def errors_to_lint_result(self, rel_fname, errors):
        if not errors:
            return

        linenums = []
        filenames_linenums = find_filenames_and_linenums(errors, [rel_fname])
        if filenames_linenums:
            filename, linenums = next(iter(filenames_linenums.items()))
            linenums = [num - 1 for num in linenums]
            Log.debug("Extracted line numbers from errors", file=rel_fname, line_count=len(linenums))

        return LintResult(text=errors, lines=linenums)

    def lint(self, fname, cmd=None):
        rel_fname = self.get_rel_fname(fname)
        Log.info("Starting lint process", file=fname, relative_file=rel_fname)
        try:
            code = Path(fname).read_text(encoding=self.encoding, errors="replace")
        except OSError as err:
            Log.error("Unable to read file", file=fname, error=err)
            print(f"Unable to read {fname}: {err}")
            return

        if cmd:
            cmd = cmd.strip()
        if not cmd:
            lang = filename_to_lang(fname)
            if not lang:
                Log.debug("Could not determine language for file", file=fname)
                return
            if self.all_lint_cmd:
                cmd = self.all_lint_cmd
            else:
                cmd = self.languages.get(lang)
                if not cmd:
                    Log.debug("No linter available for language", language=lang, file=fname)

        Log.debug("Selected linter", file=fname, linter=cmd if not callable(cmd) else cmd.__name__)
        if callable(cmd):
            lintres = cmd(fname, rel_fname, code)
        elif cmd:
            lintres = self.run_cmd(cmd, rel_fname, code)
        else:
            lintres = basic_lint(rel_fname, code)

        if not lintres:
            Log.info("No lint issues found", file=fname)
            return

        Log.info("Lint issues found", file=fname, issue_count=len(lintres.lines))
        res = "# Fix any errors below, if possible.\n\n"
        res += lintres.text
        res += "\n"
        res += tree_context(rel_fname, code, lintres.lines)

        return res

    def py_lint(self, fname, rel_fname, code):
        Log.debug("Running Python linters", file=rel_fname)
        basic_res = basic_lint(rel_fname, code)
        compile_res = lint_python_compile(fname, code)
        flake_res = self.flake8_lint(rel_fname)

        text = ""
        lines = set()
        for res in [basic_res, compile_res, flake_res]:
            if not res:
                continue
            if text:
                text += "\n"
            text += res.text
            lines.update(res.lines)

        if text or lines:
            Log.info("Python lint issues found", file=rel_fname, issue_count=len(lines))
            return LintResult(text, lines)
        else:
            Log.debug("No Python lint issues found", file=rel_fname)

    def flake8_lint(self, rel_fname):
        fatal = "E9,F821,F823,F831,F406,F407,F701,F702,F704,F706"
        flake8_cmd = [
            sys.executable,
            "-m",
            "flake8",
            f"--select={fatal}",
            "--show-source",
            "--isolated",
            rel_fname,
        ]

        Log.debug("Running flake8", file=rel_fname, select=fatal)
        text = f"## Running: {' '.join(flake8_cmd)}\n\n"

        try:
            result = subprocess.run(
                flake8_cmd,
                capture_output=True,
                text=True,
                check=False,
                encoding=self.encoding,
                errors="replace",
                cwd=self.root,
            )
            errors = result.stdout + result.stderr
        except Exception as e:
            Log.error("Error running flake8", file=rel_fname, error=e)
            errors = f"Error running flake8: {str(e)}"

        if not errors:
            Log.debug("No flake8 issues found", file=rel_fname)
            return

        Log.info("Flake8 issues found", file=rel_fname)
        text += errors
        return self.errors_to_lint_result(rel_fname, text)


@dataclass
class LintResult:
    text: str
    lines: list


def lint_python_compile(fname, code):
    Log.debug("Checking Python compile errors", file=fname)
    try:
        compile(code, fname, "exec")  # USE TRACEBACK BELOW HERE
        Log.debug("Python code compiles successfully", file=fname)
        return
    except Exception as err:
        end_lineno = getattr(err, "end_lineno", err.lineno)
        line_numbers = list(range(err.lineno - 1, end_lineno))
        
        Log.info("Python compile error detected", file=fname, error=err, line=err.lineno)

        tb_lines = traceback.format_exception(type(err), err, err.__traceback__)
        last_file_i = 0

        target = "# USE TRACEBACK"
        target += " BELOW HERE"
        for i in range(len(tb_lines)):
            if target in tb_lines[i]:
                last_file_i = i
                break

        tb_lines = tb_lines[:1] + tb_lines[last_file_i + 1 :]

    res = "".join(tb_lines)
    return LintResult(text=res, lines=line_numbers)


def basic_lint(fname, code):
    """
    Use tree-sitter to look for syntax errors, display them with tree context.
    """
    Log.debug("Starting basic lint", fname=fname)
    
    lang = filename_to_lang(fname)
    if not lang:
        Log.debug("No language detected for file", fname=fname)
        return

    # Tree-sitter linter is not capable of working with typescript #1132
    if lang == "typescript":
        Log.debug("Skipping typescript file (not supported)", fname=fname)
        return

    try:
        parser = get_parser(lang)
    except Exception as err:
        Log.error("Unable to load parser", error=err, fname=fname, lang=lang)
        print(f"Unable to load parser: {err}")
        return

    tree = parser.parse(bytes(code, "utf-8"))

    try:
        errors = traverse_tree(tree.root_node)
    except RecursionError as err:
        Log.error("RecursionError while parsing file", error=err, fname=fname)
        print(f"Unable to lint {fname} due to RecursionError")
        return

    if not errors:
        Log.debug("No errors found in file", fname=fname, lang=lang)
        return

    Log.info("Found syntax errors in file", fname=fname, lang=lang, error_count=len(errors), line_numbers=errors)
    return LintResult(text="", lines=errors)


def tree_context(fname, code, line_nums):
    Log.debug("Generating tree context", fname=fname, line_count=len(line_nums))
    
    context = TreeContext(
        fname,
        code,
        color=False,
        line_number=True,
        child_context=False,
        last_line=False,
        margin=0,
        mark_lois=True,
        loi_pad=3,
        # header_max=30,
        show_top_of_file_parent_scope=False,
    )
    line_nums = set(line_nums)
    context.add_lines_of_interest(line_nums)
    context.add_context()
    s = "s" if len(line_nums) > 1 else ""
    output = f"## See relevant line{s} below marked with █.\n\n"
    output += fname + ":\n"
    output += context.format()
    
    Log.debug("Tree context generated", fname=fname, context_length=len(output))
    return output


# Traverse the tree to find errors
def traverse_tree(node):
    errors = []
    if node.type == "ERROR" or node.is_missing:
        line_no = node.start_point[0]
        errors.append(line_no)

    for child in node.children:
        errors += traverse_tree(child)

    return errors


def find_filenames_and_linenums(text, fnames):
    """
    Search text for all occurrences of <filename>:\\d+ and make a list of them
    where <filename> is one of the filenames in the list `fnames`.
    """
    pattern = re.compile(r"(\b(?:" + "|".join(re.escape(fname) for fname in fnames) + r"):\d+\b)")
    matches = pattern.findall(text)
    result = {}
    for match in matches:
        fname, linenum = match.rsplit(":", 1)
        if fname not in result:
            result[fname] = set()
        result[fname].add(int(linenum))
    return result


def main():
    """
    Main function to parse files provided as command line arguments.
    """
    if len(sys.argv) < 2:
        Log.warn("No files provided for linting")
        print("Usage: python linter.py <file1> <file2> ...")
        sys.exit(1)

    Log.info("Starting linting process", file_count=len(sys.argv[1:]))
    linter = Linter(root=os.getcwd())
    for file_path in sys.argv[1:]:
        Log.debug("Linting file", file_path=file_path)
        errors = linter.lint(file_path)
        if errors:
            Log.info("Found errors in file", file_path=file_path)
            print(errors)
    
    Log.info("Completed linting all files", file_count=len(sys.argv[1:]))


if __name__ == "__main__":
    main()
