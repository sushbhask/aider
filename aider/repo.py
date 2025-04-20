import os
import time
from pathlib import Path, PurePosixPath

try:
    import git

    ANY_GIT_ERROR = [
        git.exc.ODBError,
        git.exc.GitError,
        git.exc.InvalidGitRepositoryError,
        git.exc.GitCommandNotFound,
    ]
except ImportError:
    git = None
    ANY_GIT_ERROR = []

import pathspec

from aider import prompts, utils

from .dump import dump  # noqa: F401
from treebeardhq import Log


ANY_GIT_ERROR += [
    OSError,
    IndexError,
    BufferError,
    TypeError,
    ValueError,
    AttributeError,
    AssertionError,
    TimeoutError,
]
ANY_GIT_ERROR = tuple(ANY_GIT_ERROR)


class GitRepo:
    repo = None
    aider_ignore_file = None
    aider_ignore_spec = None
    aider_ignore_ts = 0
    aider_ignore_last_check = 0
    subtree_only = False
    ignore_file_cache = {}
    git_repo_error = None

    def __init__(
        self,
        io,
        fnames,
        git_dname,
        aider_ignore_file=None,
        models=None,
        attribute_author=True,
        attribute_committer=True,
        attribute_commit_message_author=False,
        attribute_commit_message_committer=False,
        commit_prompt=None,
        subtree_only=False,
        git_commit_verify=True,
    ):
        self.io = io
        self.models = models

        self.normalized_path = {}
        self.tree_files = {}

        self.attribute_author = attribute_author
        self.attribute_committer = attribute_committer
        self.attribute_commit_message_author = attribute_commit_message_author
        self.attribute_commit_message_committer = attribute_commit_message_committer
        self.commit_prompt = commit_prompt
        self.subtree_only = subtree_only
        self.git_commit_verify = git_commit_verify
        self.ignore_file_cache = {}

        if git_dname:
            check_fnames = [git_dname]
        elif fnames:
            check_fnames = fnames
        else:
            check_fnames = ["."]

        repo_paths = []
        for fname in check_fnames:
            fname = Path(fname)
            fname = fname.resolve()

            if not fname.exists() and fname.parent.exists():
                fname = fname.parent

            try:
                repo_path = git.Repo(fname, search_parent_directories=True).working_dir
                repo_path = utils.safe_abs_path(repo_path)
                repo_paths.append(repo_path)
            except ANY_GIT_ERROR:
                pass

        num_repos = len(set(repo_paths))

        if num_repos == 0:
            Log.error("No git repositories found", check_fnames=check_fnames)
            raise FileNotFoundError
        if num_repos > 1:
            Log.error("Multiple git repositories found", repo_paths=repo_paths, num_repos=num_repos)
            self.io.tool_error("Files are in different git repos.")
            raise FileNotFoundError

        # https://github.com/gitpython-developers/GitPython/issues/427
        self.repo = git.Repo(repo_paths.pop(), odbt=git.GitDB)
        self.root = utils.safe_abs_path(self.repo.working_tree_dir)
        Log.info("Git repository initialized", root=self.root)

        if aider_ignore_file:
            self.aider_ignore_file = Path(aider_ignore_file)

    def commit(self, fnames=None, context=None, message=None, aider_edits=False):
        if not fnames and not self.repo.is_dirty():
            Log.debug("Repository is not dirty, skipping commit", fnames=fnames)
            return

        diffs = self.get_diffs(fnames)
        if not diffs:
            Log.debug("No diffs to commit", fnames=fnames)
            return

        if message:
            commit_message = message
        else:
            commit_message = self.get_commit_message(diffs, context)

        if aider_edits and self.attribute_commit_message_author:
            commit_message = "aider: " + commit_message
        elif self.attribute_commit_message_committer:
            commit_message = "aider: " + commit_message

        if not commit_message:
            Log.warn("No commit message provided, using default", fnames=fnames)
            commit_message = "(no commit message provided)"

        full_commit_message = commit_message
        # if context:
        #    full_commit_message += "\n\n# Aider chat conversation:\n\n" + context

        cmd = ["-m", full_commit_message]
        if not self.git_commit_verify:
            cmd.append("--no-verify")
        if fnames:
            fnames = [str(self.abs_root_path(fn)) for fn in fnames]
            for fname in fnames:
                try:
                    self.repo.git.add(fname)
                    Log.debug("Added file to commit", fname=fname)
                except ANY_GIT_ERROR as err:
                    Log.error("Failed to add file to commit", fname=fname, error=err)
                    self.io.tool_error(f"Unable to add {fname}: {err}")
            cmd += ["--"] + fnames
        else:
            cmd += ["-a"]

        original_user_name = self.repo.git.config("--get", "user.name")
        original_committer_name_env = os.environ.get("GIT_COMMITTER_NAME")
        committer_name = f"{original_user_name} (aider)"

        if self.attribute_committer:
            os.environ["GIT_COMMITTER_NAME"] = committer_name
            Log.debug("Set committer name", name=committer_name)

        if aider_edits and self.attribute_author:
            original_author_name_env = os.environ.get("GIT_AUTHOR_NAME")
            os.environ["GIT_AUTHOR_NAME"] = committer_name
            Log.debug("Set author name", name=committer_name)

        try:
            self.repo.git.commit(cmd)
            commit_hash = self.get_head_commit_sha(short=True)
            Log.info("Successfully committed changes", commit_hash=commit_hash, commit_message=commit_message, fnames=fnames)
            self.io.tool_output(f"Commit {commit_hash} {commit_message}", bold=True)
            return commit_hash, commit_message
        except ANY_GIT_ERROR as err:
            Log.error("Failed to commit changes", error=err, cmd=cmd)
            self.io.tool_error(f"Unable to commit: {err}")
        finally:
            # Restore the env
            if self.attribute_committer:
                if original_committer_name_env is not None:
                    os.environ["GIT_COMMITTER_NAME"] = original_committer_name_env
                else:
                    del os.environ["GIT_COMMITTER_NAME"]

            if aider_edits and self.attribute_author:
                if original_author_name_env is not None:
                    os.environ["GIT_AUTHOR_NAME"] = original_author_name_env
                else:
                    del os.environ["GIT_AUTHOR_NAME"]

    def get_rel_repo_dir(self):
        try:
            return os.path.relpath(self.repo.git_dir, os.getcwd())
        except (ValueError, OSError):
            return self.repo.git_dir

    def get_commit_message(self, diffs, context):
        diffs = "# Diffs:\n" + diffs

        content = ""
        if context:
            content += context + "\n"
        content += diffs

        system_content = self.commit_prompt or prompts.commit_system
        messages = [
            dict(role="system", content=system_content),
            dict(role="user", content=content),
        ]

        commit_message = None
        for model in self.models:
            num_tokens = model.token_count(messages)
            max_tokens = model.info.get("max_input_tokens") or 0
            if max_tokens and num_tokens > max_tokens:
                Log.debug("Model token count exceeds max input tokens", model=model.model_name, num_tokens=num_tokens, max_tokens=max_tokens)
                continue
            Log.debug("Attempting to generate commit message with model", model=model.model_name, num_tokens=num_tokens)
            commit_message = model.simple_send_with_retries(messages)
            if commit_message:
                Log.debug("Successfully generated commit message", model=model.model_name)
                break

        if not commit_message:
            self.io.tool_error("Failed to generate commit message!")
            Log.error("Failed to generate commit message", models=[m.model_name for m in self.models])
            return

        commit_message = commit_message.strip()
        if commit_message and commit_message[0] == '"' and commit_message[-1] == '"':
            commit_message = commit_message[1:-1].strip()

        Log.info("Generated commit message", message_length=len(commit_message))
        return commit_message

    def get_diffs(self, fnames=None):
        # We always want diffs of index and working dir
        Log.debug("Getting diffs", fnames=fnames)

        current_branch_has_commits = False
        try:
            active_branch = self.repo.active_branch
            try:
                commits = self.repo.iter_commits(active_branch)
                current_branch_has_commits = any(commits)
                Log.debug("Checked if current branch has commits", branch=active_branch.name, has_commits=current_branch_has_commits)
            except ANY_GIT_ERROR as err:
                Log.warn("Failed to check commits on active branch", error=err)
                pass
        except (TypeError,) + ANY_GIT_ERROR as err:
            Log.warn("Failed to get active branch", error=err)
            pass

        if not fnames:
            fnames = []

        diffs = ""
        for fname in fnames:
            if not self.path_in_repo(fname):
                diffs += f"Added {fname}\n"
                Log.debug("Added new file to diffs", file=fname)

        try:
            if current_branch_has_commits:
                args = ["HEAD", "--"] + list(fnames)
                Log.debug("Getting diffs from HEAD", args=args)
                diffs += self.repo.git.diff(*args)
                return diffs

            wd_args = ["--"] + list(fnames)
            index_args = ["--cached"] + wd_args
            
            Log.debug("Getting diffs from index", args=index_args)
            diffs += self.repo.git.diff(*index_args)
            
            Log.debug("Getting diffs from working directory", args=wd_args)
            diffs += self.repo.git.diff(*wd_args)

            Log.info("Generated diffs", diff_length=len(diffs), file_count=len(fnames))
            return diffs
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to diff: {err}")
            Log.error("Unable to generate diffs", error=err, fnames=fnames)

    def diff_commits(self, pretty, from_commit, to_commit):
        Log.debug("Generating diff between commits", from_commit=from_commit, to_commit=to_commit, pretty=pretty)
        args = []
        if pretty:
            args += ["--color"]
        else:
            args += ["--color=never"]

        args += [from_commit, to_commit]
        diffs = self.repo.git.diff(*args)

        Log.info("Generated diff between commits", from_commit=from_commit, to_commit=to_commit, diff_length=len(diffs))
        return diffs

    def get_tracked_files(self):
        if not self.repo:
            Log.debug("No repository available, returning empty file list")
            return []

        try:
            commit = self.repo.head.commit
        except ValueError as err:
            Log.warn("No commits in repository", error=err)
            commit = None
        except ANY_GIT_ERROR as err:
            self.git_repo_error = err
            self.io.tool_error(f"Unable to list files in git repo: {err}")
            self.io.tool_output("Is your git repo corrupted?")
            Log.error("Failed to get repository HEAD", error=err)
            return []

        files = set()
        if commit:
            if commit in self.tree_files:
                Log.debug("Using cached tree files for commit", commit=commit.hexsha[:7])
                files = self.tree_files[commit]
            else:
                try:
                    Log.debug("Traversing commit tree", commit=commit.hexsha[:7])
                    iterator = commit.tree.traverse()
                    blob = None  # Initialize blob
                    while True:
                        try:
                            blob = next(iterator)
                            if blob.type == "blob":  # blob is a file
                                files.add(blob.path)
                        except IndexError:
                            # Handle potential index error during tree traversal
                            # without relying on potentially unassigned 'blob'
                            self.io.tool_warning(
                                "GitRepo: Index error encountered while reading git tree object."
                                " Skipping."
                            )
                            Log.warn("Index error encountered while reading git tree object")
                            continue
                        except StopIteration:
                            break
                except ANY_GIT_ERROR as err:
                    self.git_repo_error = err
                    self.io.tool_error(f"Unable to list files in git repo: {err}")
                    self.io.tool_output("Is your git repo corrupted?")
                    Log.error("Failed to traverse commit tree", error=err, commit=commit.hexsha[:7])
                    return []
                files = set(self.normalize_path(path) for path in files)
                self.tree_files[commit] = set(files)
                Log.debug("Cached normalized paths for commit", commit=commit.hexsha[:7], file_count=len(files))

        # Add staged files
        index = self.repo.index
        try:
            staged_files = [path for path, _ in index.entries.keys()]
            files.update(self.normalize_path(path) for path in staged_files)
            Log.debug("Added staged files to tracked files list", staged_count=len(staged_files))
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to read staged files: {err}")
            Log.error("Failed to read staged files", error=err)

        res = [fname for fname in files if not self.ignored_file(fname)]
        
        Log.info("Retrieved tracked files", total_files=len(files), filtered_files=len(res))
        return res

    def normalize_path(self, path):
        orig_path = path
        res = self.normalized_path.get(orig_path)
        if res:
            return res

        path = str(Path(PurePosixPath((Path(self.root) / path).relative_to(self.root))))
        self.normalized_path[orig_path] = path
        return path

    def refresh_aider_ignore(self):
        if not self.aider_ignore_file:
            return

        current_time = time.time()
        if current_time - self.aider_ignore_last_check < 1:
            return

        self.aider_ignore_last_check = current_time

        if not self.aider_ignore_file.is_file():
            return

        mtime = self.aider_ignore_file.stat().st_mtime
        if mtime != self.aider_ignore_ts:
            Log.debug("Updating aider ignore file cache", file=str(self.aider_ignore_file), old_ts=self.aider_ignore_ts, new_ts=mtime)
            self.aider_ignore_ts = mtime
            self.ignore_file_cache = {}
            lines = self.aider_ignore_file.read_text().splitlines()
            self.aider_ignore_spec = pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern,
                lines,
            )
            Log.info("Updated aider ignore specification", patterns_count=len(lines))

    def git_ignored_file(self, path):
        if not self.repo:
            return
        try:
            if self.repo.ignored(path):
                return True
        except ANY_GIT_ERROR:
            return False

    def ignored_file(self, fname):
        self.refresh_aider_ignore()

        if fname in self.ignore_file_cache:
            return self.ignore_file_cache[fname]

        result = self.ignored_file_raw(fname)
        self.ignore_file_cache[fname] = result
        return result

    def ignored_file_raw(self, fname):
        if self.subtree_only:
            try:
                fname_path = Path(self.normalize_path(fname))
                cwd_path = Path.cwd().resolve().relative_to(Path(self.root).resolve())
            except ValueError:
                # Issue #1524
                # ValueError: 'C:\\dev\\squid-certbot' is not in the subpath of
                # 'C:\\dev\\squid-certbot'
                # Clearly, fname is not under cwd... so ignore it
                Log.debug("File not in working directory subtree", fname=fname)
                return True

            if cwd_path not in fname_path.parents and fname_path != cwd_path:
                Log.debug("File outside current working directory", fname=fname, cwd_path=str(cwd_path), fname_path=str(fname_path))
                return True

        if not self.aider_ignore_file or not self.aider_ignore_file.is_file():
            return False

        try:
            fname = self.normalize_path(fname)
        except ValueError:
            Log.debug("Could not normalize path", fname=fname)
            return True

        is_ignored = self.aider_ignore_spec.match_file(fname)
        if is_ignored:
            Log.debug("File matched aider ignore patterns", fname=fname)
        return is_ignored

    def path_in_repo(self, path):
        if not self.repo:
            return
        if not path:
            return

        tracked_files = set(self.get_tracked_files())
        normalized_path = self.normalize_path(path)
        result = normalized_path in tracked_files
        Log.debug("Checking if path is in repo", path=path, normalized_path=normalized_path, is_tracked=result)
        return result

    def abs_root_path(self, path):
        res = Path(self.root) / path
        return utils.safe_abs_path(res)

    def get_dirty_files(self):
        """
        Returns a list of all files which are dirty (not committed), either staged or in the working
        directory.
        """
        dirty_files = set()

        # Get staged files
        staged_files = self.repo.git.diff("--name-only", "--cached").splitlines()
        dirty_files.update(staged_files)

        # Get unstaged files
        unstaged_files = self.repo.git.diff("--name-only").splitlines()
        dirty_files.update(unstaged_files)

        Log.debug("Found dirty files", count=len(dirty_files), staged_count=len(staged_files), unstaged_count=len(unstaged_files))
        return list(dirty_files)

    def is_dirty(self, path=None):
        if path and not self.path_in_repo(path):
            Log.debug("Path not in repo, considering it dirty", path=path)
            return True

        result = self.repo.is_dirty(path=path)
        Log.debug("Checking if repo is dirty", path=path, is_dirty=result)
        return result

    def get_head_commit(self):
        try:
            return self.repo.head.commit
        except (ValueError,) + ANY_GIT_ERROR as e:
            Log.debug("Could not get head commit", error=e)
            return None

    def get_head_commit_sha(self, short=False):
        commit = self.get_head_commit()
        if not commit:
            return
        if short:
            return commit.hexsha[:7]
        return commit.hexsha

    def get_head_commit_message(self, default=None):
        commit = self.get_head_commit()
        if not commit:
            Log.debug("No head commit, using default message", default=default)
            return default
        return commit.message
