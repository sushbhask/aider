#!/usr/bin/env python

import os
import random
import sys

import streamlit as st

from aider import urls
from aider.coders import Coder
from aider.dump import dump  # noqa: F401
from aider.io import InputOutput
from aider.main import main as cli_main
from aider.scrape import Scraper
from treebeardhq import Log



class CaptureIO(InputOutput):
    lines = []

    def tool_output(self, msg, log_only=False):
        if not log_only:
            self.lines.append(msg)
            Log.debug("Captured tool output", msg=msg, log_only=log_only, lines_count=len(self.lines))
        super().tool_output(msg, log_only=log_only)

    def tool_error(self, msg):
        self.lines.append(msg)
        Log.debug("Captured tool error", msg=msg, lines_count=len(self.lines))
        super().tool_error(msg)

    def tool_warning(self, msg):
        self.lines.append(msg)
        Log.debug("Captured tool warning", msg=msg, lines_count=len(self.lines))
        super().tool_warning(msg)

    def get_captured_lines(self):
        lines = self.lines
        count = len(lines)
        self.lines = []
        Log.debug("Retrieved captured lines", count=count)
        return lines


def search(text=None):
    Log.debug("Starting file search", search_text=text)
    results = []
    for root, _, files in os.walk("aider"):
        for file in files:
            path = os.path.join(root, file)
            if not text or text in path:
                results.append(path)
    # dump(results)
    
    Log.debug("Completed file search", search_text=text, results_count=len(results))
    return results


# Keep state as a resource, which survives browser reloads (since Coder does too)
class State:
    keys = set()

    def init(self, key, val=None):
        if key in self.keys:
            return

        self.keys.add(key)
        setattr(self, key, val)
        Log.debug("Initialized state key", key=key, value_type=type(val).__name__)
        return True


@st.cache_resource
def get_state():
    Log.debug("Getting application state")
    return State()


@st.cache_resource
def get_coder():
    Log.info("Initializing coder")
    try:
        coder = cli_main(return_coder=True)
        if not isinstance(coder, Coder):
            error = ValueError(coder)
            Log.error("Invalid coder instance returned", error=error, returned_type=type(coder).__name__)
            raise error
        if not coder.repo:
            error = ValueError("GUI can currently only be used inside a git repo")
            Log.error("No git repository found", error=error)
            raise error

        io = CaptureIO(
            pretty=False,
            yes=True,
            dry_run=coder.io.dry_run,
            encoding=coder.io.encoding,
        )
        # coder.io = io # this breaks the input_history
        coder.commands.io = io

        for line in coder.get_announcements():
            coder.io.tool_output(line)

        Log.info("Coder initialized successfully", has_repo=bool(coder.repo))
        return coder
    except Exception as e:
        Log.error("Failed to initialize coder", error=e)
        raise


class GUI:
    prompt = None
    prompt_as = "user"
    last_undo_empty = None
    recent_msgs_empty = None
    web_content_empty = None

    def announce(self):
        lines = self.coder.get_announcements()
        lines = "  \n".join(lines)
        Log.debug("Generated announcement message", announcement_count=len(lines) if lines else 0)
        return lines

    def show_edit_info(self, edit):
        commit_hash = edit.get("commit_hash")
        commit_message = edit.get("commit_message")
        diff = edit.get("diff")
        fnames = edit.get("fnames")
        if fnames:
            fnames = sorted(fnames)

        Log.debug("Processing edit info", has_commit=bool(commit_hash), has_files=bool(fnames), file_count=len(fnames) if fnames else 0)
        
        if not commit_hash and not fnames:
            Log.debug("No commit hash or files to display, skipping edit info")
            return

        show_undo = False
        res = ""
        if commit_hash:
            res += f"Commit `{commit_hash}`: {commit_message}  \n"
            if commit_hash == self.coder.last_aider_commit_hash:
                show_undo = True
                Log.debug("Edit is from last commit, enabling undo option", commit_hash=commit_hash)

        if fnames:
            fnames_display = [f"`{fname}`" for fname in fnames]
            fnames_display = ", ".join(fnames_display)
            res += f"Applied edits to {fnames_display}."

        Log.info("Displaying edit information", has_diff=bool(diff), show_undo=show_undo, file_count=len(fnames) if fnames else 0)
        
        if diff:
            with st.expander(res):
                st.code(diff, language="diff")
                if show_undo:
                    self.add_undo(commit_hash)
        else:
            with st.container(border=True):
                st.write(res)
                if show_undo:
                    self.add_undo(commit_hash)

    def add_undo(self, commit_hash):
        Log.debug("Preparing undo UI for commit", commit_hash=commit_hash)
        if self.last_undo_empty:
            self.last_undo_empty.empty()

        self.last_undo_empty = st.empty()
        undone = self.state.last_undone_commit_hash == commit_hash
        if not undone:
            Log.debug("Showing undo button for commit", commit_hash=commit_hash, already_undone=undone)
            with self.last_undo_empty:
                if self.button(f"Undo commit `{commit_hash}`", key=f"undo_{commit_hash}"):
                    self.do_undo(commit_hash)

    def do_sidebar(self):
        Log.debug("Rendering sidebar UI components")
        with st.sidebar:
            st.title("Aider")
            self.do_add_to_chat()
            self.do_recent_msgs()
            self.do_clear_chat_history()

            st.warning(
                "This browser version of aider is experimental. Please share feedback in [GitHub"
                " issues](https://github.com/Aider-AI/aider/issues)."
            )

    def do_settings_tab(self):
        pass

    def do_recommended_actions(self):
        text = "Aider works best when your code is stored in a git repo.  \n"
        text += f"[See the FAQ for more info]({urls.git})"

        with st.expander("Recommended actions", expanded=True):
            with st.popover("Create a git repo to track changes"):
                st.write(text)
                self.button("Create git repo", key=random.random(), help="?")

            with st.popover("Update your `.gitignore` file"):
                st.write("It's best to keep aider's internal files out of your git repo.")
                self.button("Add `.aider*` to `.gitignore`", key=random.random(), help="?")

    def do_add_to_chat(self):
        Log.debug("Rendering file and web page addition UI")
        self.do_add_files()
        self.do_add_web_page()

    def do_add_files(self):
        all_files = self.coder.get_all_relative_files()
        current_files = self.state.initial_inchat_files
        
        Log.debug("Rendering file selection UI", total_files=len(all_files), current_chat_files=len(current_files))
        
        fnames = st.multiselect(
            "Add files to the chat",
            all_files,
            default=current_files,
            placeholder="Files to edit",
            disabled=self.prompt_pending(),
            help=(
                "Only add the files that need to be *edited* for the task you are working"
                " on. Aider will pull in other relevant code to provide context to the LLM."
            ),
        )

        current_inchat_files = self.coder.get_inchat_relative_files()
        
        for fname in fnames:
            if fname not in current_inchat_files:
                Log.info("Adding file to chat", filename=fname)
                self.coder.add_rel_fname(fname)
                self.info(f"Added {fname} to the chat")

        for fname in current_inchat_files:
            if fname not in fnames:
                Log.info("Removing file from chat", filename=fname)
                self.coder.drop_rel_fname(fname)
                self.info(f"Removed {fname} from the chat")

    def do_add_web_page(self):
        with st.popover("Add a web page to the chat"):
            self.do_web()

    def do_add_image(self):
        with st.popover("Add image"):
            st.markdown("Hello World 👋")
            st.file_uploader("Image file", disabled=self.prompt_pending())

    def do_run_shell(self):
        with st.popover("Run shell commands, tests, etc"):
            st.markdown(
                "Run a shell command and optionally share the output with the LLM. This is"
                " a great way to run your program or run tests and have the LLM fix bugs."
            )
            st.text_input("Command:")
            st.radio(
                "Share the command output with the LLM?",
                [
                    "Review the output and decide whether to share",
                    "Automatically share the output on non-zero exit code (ie, if any tests fail)",
                ],
            )
            st.selectbox(
                "Recent commands",
                [
                    "my_app.py --doit",
                    "my_app.py --cleanup",
                ],
                disabled=self.prompt_pending(),
            )

    def do_tokens_and_cost(self):
        with st.expander("Tokens and costs", expanded=True):
            pass

    def do_show_token_usage(self):
        with st.popover("Show token usage"):
            st.write("hi")

    def do_clear_chat_history(self):
        text = "Saves tokens, reduces confusion"
        if self.button("Clear chat history", help=text):
            Log.info("Clearing chat history")
            self.coder.done_messages = []
            self.coder.cur_messages = []
            self.info("Cleared chat history. Now the LLM can't see anything before this line.")

    def do_show_metrics(self):
        st.metric("Cost of last message send & reply", "$0.0019", help="foo")
        st.metric("Cost to send next message", "$0.0013", help="foo")
        st.metric("Total cost this session", "$0.22")

    def do_git(self):
        with st.expander("Git", expanded=False):
            self.button("Commit any pending changes")
            with st.popover("Run git command"):
                st.markdown("## Run git command")
                st.text_input("git", value="git ")
                self.button("Run")
                st.selectbox(
                    "Recent git commands",
                    [
                        "git checkout -b experiment",
                        "git stash",
                    ],
                    disabled=self.prompt_pending(),
                )

    def do_recent_msgs(self):
        if not self.recent_msgs_empty:
            self.recent_msgs_empty = st.empty()

        if self.prompt_pending():
            Log.debug("Clearing recent_msgs_empty due to pending prompt")
            self.recent_msgs_empty.empty()
            self.state.recent_msgs_num += 1

        with self.recent_msgs_empty:
            self.old_prompt = st.selectbox(
                "Resend a recent chat message",
                self.state.input_history,
                placeholder="Choose a recent chat message",
                # label_visibility="collapsed",
                index=None,
                key=f"recent_msgs_{self.state.recent_msgs_num}",
                disabled=self.prompt_pending(),
            )
            if self.old_prompt:
                Log.debug("User selected a previous message to resend", message_text=self.old_prompt)
                self.prompt = self.old_prompt

    def do_messages_container(self):
        self.messages = st.container()

        # stuff a bunch of vertical whitespace at the top
        # to get all the chat text to the bottom
        # self.messages.container(height=300, border=False)

        with self.messages:
            for msg in self.state.messages:
                role = msg["role"]

                if role == "edit":
                    self.show_edit_info(msg)
                elif role == "info":
                    st.info(msg["content"])
                elif role == "text":
                    text = msg["content"]
                    line = text.splitlines()[0]
                    with self.messages.expander(line):
                        st.text(text)
                elif role in ("user", "assistant"):
                    with st.chat_message(role):
                        st.write(msg["content"])
                        # self.cost()
                else:
                    st.dict(msg)

    def initialize_state(self):
        Log.debug("Initializing GUI state")
        messages = [
            dict(role="info", content=self.announce()),
            dict(role="assistant", content="How can I help you?"),
        ]

        self.state.init("messages", messages)
        self.state.init("last_aider_commit_hash", self.coder.last_aider_commit_hash)
        self.state.init("last_undone_commit_hash")
        self.state.init("recent_msgs_num", 0)
        self.state.init("web_content_num", 0)
        self.state.init("prompt")
        self.state.init("scraper")

        self.state.init("initial_inchat_files", self.coder.get_inchat_relative_files())

        if "input_history" not in self.state.keys:
            input_history = list(self.coder.io.get_input_history())
            seen = set()
            input_history = [x for x in input_history if not (x in seen or seen.add(x))]
            self.state.input_history = input_history
            self.state.keys.add("input_history")
            Log.debug("Initialized input history", history_count=len(input_history))

    def button(self, args, **kwargs):
        "Create a button, disabled if prompt pending"

        # Force everything to be disabled if there is a prompt pending
        if self.prompt_pending():
            kwargs["disabled"] = True

        return st.button(args, **kwargs)

    def __init__(self):
        self.coder = get_coder()
        self.state = get_state()

        # Force the coder to cooperate, regardless of cmd line args
        self.coder.yield_stream = True
        self.coder.stream = True
        self.coder.pretty = False

        self.initialize_state()

        self.do_messages_container()
        self.do_sidebar()

        user_inp = st.chat_input("Say something")
        if user_inp:
            Log.debug("Received user input from chat input", input_length=len(user_inp))
            self.prompt = user_inp

        if self.prompt_pending():
            self.process_chat()

        if not self.prompt:
            return

        self.state.prompt = self.prompt

        if self.prompt_as == "user":
            self.coder.io.add_to_input_history(self.prompt)

        self.state.input_history.append(self.prompt)

        if self.prompt_as:
            self.state.messages.append({"role": self.prompt_as, "content": self.prompt})
        if self.prompt_as == "user":
            with self.messages.chat_message("user"):
                st.write(self.prompt)
        elif self.prompt_as == "text":
            line = self.prompt.splitlines()[0]
            line += "??"
            with self.messages.expander(line):
                st.text(self.prompt)

        # re-render the UI for the prompt_pending state
        st.rerun()

    def prompt_pending(self):
        return self.state.prompt is not None

    def cost(self):
        cost = random.random() * 0.003 + 0.001
        st.caption(f"${cost:0.4f}")

    def process_chat(self):
        Log.info("Processing chat message", prompt_as=self.prompt_as)
        prompt = self.state.prompt
        self.state.prompt = None

        # This duplicates logic from within Coder
        self.num_reflections = 0
        self.max_reflections = 3

        while prompt:
            with self.messages.chat_message("assistant"):
                Log.debug("Sending prompt to coder and streaming response")
                res = st.write_stream(self.coder.run_stream(prompt))
                self.state.messages.append({"role": "assistant", "content": res})
                # self.cost()

            prompt = None
            if self.coder.reflected_message:
                if self.num_reflections < self.max_reflections:
                    self.num_reflections += 1
                    Log.debug("Processing reflection", 
                             reflection_number=self.num_reflections, 
                             max_reflections=self.max_reflections)
                    self.info(self.coder.reflected_message)
                    prompt = self.coder.reflected_message
                else:
                    Log.warn("Max reflections reached", max_reflections=self.max_reflections)

        with self.messages:
            edit = dict(
                role="edit",
                fnames=self.coder.aider_edited_files,
            )
            if self.state.last_aider_commit_hash != self.coder.last_aider_commit_hash:
                Log.info("New commit detected", 
                        commit_hash=self.coder.last_aider_commit_hash, 
                        files_edited=self.coder.aider_edited_files)
                edit["commit_hash"] = self.coder.last_aider_commit_hash
                edit["commit_message"] = self.coder.last_aider_commit_message
                commits = f"{self.coder.last_aider_commit_hash}~1"
                diff = self.coder.repo.diff_commits(
                    self.coder.pretty,
                    commits,
                    self.coder.last_aider_commit_hash,
                )
                edit["diff"] = diff
                self.state.last_aider_commit_hash = self.coder.last_aider_commit_hash

            self.state.messages.append(edit)
            self.show_edit_info(edit)

        # re-render the UI for the non-prompt_pending state
        st.rerun()

    def info(self, message, echo=True):
        info = dict(role="info", content=message)
        self.state.messages.append(info)

        # We will render the tail of the messages array after this call
        if echo:
            self.messages.info(message)

    def do_web(self):
        Log.info("Processing web content input", state_web_content_num=self.state.web_content_num)
        st.markdown("Add the text content of a web page to the chat")

        if not self.web_content_empty:
            self.web_content_empty = st.empty()

        if self.prompt_pending():
            Log.debug("Prompt pending, emptying web content input", prompt_pending=True)
            self.web_content_empty.empty()
            self.state.web_content_num += 1

        with self.web_content_empty:
            self.web_content = st.text_input(
                "URL",
                placeholder="https://...",
                key=f"web_content_{self.state.web_content_num}",
            )

        if not self.web_content:
            Log.debug("No web content URL provided", web_content=self.web_content)
            return

        url = self.web_content
        Log.info("Processing web content URL", url=url)

        if not self.state.scraper:
            Log.debug("Initializing web scraper")
            self.scraper = Scraper(print_error=self.info)

        try:
            content = self.scraper.scrape(url) or ""
            if content.strip():
                Log.info("Successfully scraped web content", url=url, content_length=len(content))
                content = f"{url}\n\n" + content
                self.prompt = content
                self.prompt_as = "text"
            else:
                Log.warn("No content found for URL", url=url)
                self.info(f"No web content found for `{url}`.")
                self.web_content = None
        except Exception as e:
            Log.error("Error scraping web content", url=url, error=e)
            self.info(f"Error scraping content from `{url}`: {str(e)}")
            self.web_content = None

    def do_undo(self, commit_hash):
        Log.info("Processing undo request", commit_hash=commit_hash)
        self.last_undo_empty.empty()

        if (
            self.state.last_aider_commit_hash != commit_hash
            or self.coder.last_aider_commit_hash != commit_hash
        ):
            Log.warn("Cannot undo - commit is not the latest", 
                     commit_hash=commit_hash, 
                     state_last_commit=self.state.last_aider_commit_hash, 
                     coder_last_commit=self.coder.last_aider_commit_hash)
            self.info(f"Commit `{commit_hash}` is not the latest commit.")
            return

        Log.debug("Capturing lines before undo")
        self.coder.commands.io.get_captured_lines()
        
        try:
            reply = self.coder.commands.cmd_undo(None)
            lines = self.coder.commands.io.get_captured_lines()
            
            lines = "\n".join(lines)
            lines = lines.splitlines()
            lines = "  \n".join(lines)
            self.info(lines, echo=False)
            
            self.state.last_undone_commit_hash = commit_hash
            
            Log.info("Undo completed successfully", 
                    commit_hash=commit_hash, 
                    has_reply=bool(reply),
                    lines_count=len(lines.splitlines()) if lines else 0)
            
            if reply:
                self.prompt_as = None
                self.prompt = reply
        except Exception as e:
            Log.error("Error during undo operation", commit_hash=commit_hash, error=e)
            self.info(f"Error during undo: {str(e)}")


def gui_main():
    Log.info("Starting GUI main function")
    st.set_page_config(
        layout="wide",
        page_title="Aider",
        page_icon=urls.favicon,
        menu_items={
            "Get Help": urls.website,
            "Report a bug": "https://github.com/Aider-AI/aider/issues",
            "About": "# Aider\nAI pair programming in your browser.",
        },
    )
    Log.debug("Streamlit page config set")

    # config_options = st.config._config_options
    # for key, value in config_options.items():
    #    print(f"{key}: {value.value}")

    GUI()
    Log.info("GUI initialized and running")


if __name__ == "__main__":
    Log.info("Starting Aider application")
    status = gui_main()
    Log.info("Application finished", status=status)
    sys.exit(status)
