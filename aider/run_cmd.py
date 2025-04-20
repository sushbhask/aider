import os
import platform
import subprocess
import sys
from io import BytesIO

import pexpect
import psutil
from treebeardhq import Log



def run_cmd(command, verbose=False, error_print=None, cwd=None):
    try:
        Log.debug("Starting command execution", command=command, verbose=verbose, cwd=cwd)
        if sys.stdin.isatty() and hasattr(pexpect, "spawn") and platform.system() != "Windows":
            Log.debug("Using pexpect for command execution", command=command)
            return run_cmd_pexpect(command, verbose, cwd)

        Log.debug("Using subprocess for command execution", command=command)
        return run_cmd_subprocess(command, verbose, cwd)
    except OSError as e:
        error_message = f"Error occurred while running command '{command}': {str(e)}"
        Log.error("Command execution failed with OSError", error=e, command=command)
        if error_print is None:
            print(error_message)
        else:
            error_print(error_message)
        return 1, error_message


def get_windows_parent_process_name():
    try:
        current_process = psutil.Process()
        Log.debug("Finding Windows parent process")
        while True:
            parent = current_process.parent()
            if parent is None:
                break
            parent_name = parent.name().lower()
            if parent_name in ["powershell.exe", "cmd.exe"]:
                Log.debug("Found parent shell process", parent_name=parent_name)
                return parent_name
            current_process = parent
        Log.debug("No relevant parent shell process found")
        return None
    except Exception as e:
        Log.error("Error determining Windows parent process", error=e)
        return None


def run_cmd_subprocess(command, verbose=False, cwd=None, encoding=sys.stdout.encoding):
    if verbose:
        print("Using run_cmd_subprocess:", command)

    try:
        shell = os.environ.get("SHELL", "/bin/sh")
        parent_process = None

        # Determine the appropriate shell
        if platform.system() == "Windows":
            parent_process = get_windows_parent_process_name()
            if parent_process == "powershell.exe":
                Log.debug("Using PowerShell for command execution", original_command=command)
                command = f"powershell -Command {command}"

        if verbose:
            print("Running command:", command)
            print("SHELL:", shell)
            if platform.system() == "Windows":
                print("Parent process:", parent_process)

        Log.debug("Starting subprocess", command=command, shell=shell, parent_process=parent_process, cwd=cwd)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            encoding=encoding,
            errors="replace",
            bufsize=0,  # Set bufsize to 0 for unbuffered output
            universal_newlines=True,
            cwd=cwd,
        )

        output = []
        while True:
            chunk = process.stdout.read(1)
            if not chunk:
                break
            print(chunk, end="", flush=True)  # Print the chunk in real-time
            output.append(chunk)  # Store the chunk for later use

        process.wait()
        output_str = "".join(output)
        Log.info("Subprocess completed", command=command, return_code=process.returncode, output_length=len(output_str))
        return process.returncode, output_str
    except Exception as e:
        Log.error("Subprocess execution failed", error=e, command=command)
        return 1, str(e)


def run_cmd_pexpect(command, verbose=False, cwd=None):
    """
    Run a shell command interactively using pexpect, capturing all output.

    :param command: The command to run as a string.
    :param verbose: If True, print output in real-time.
    :return: A tuple containing (exit_status, output)
    """
    if verbose:
        print("Using run_cmd_pexpect:", command)

    output = BytesIO()

    def output_callback(b):
        output.write(b)
        return b

    try:
        # Use the SHELL environment variable, falling back to /bin/sh if not set
        shell = os.environ.get("SHELL", "/bin/sh")
        if verbose:
            print("With shell:", shell)

        Log.debug("Setting up pexpect execution", command=command, shell=shell, cwd=cwd)
        
        if os.path.exists(shell):
            # Use the shell from SHELL environment variable
            if verbose:
                print("Running pexpect.spawn with shell:", shell)
            Log.debug("Using existing shell for pexpect", shell=shell)
            child = pexpect.spawn(shell, args=["-i", "-c", command], encoding="utf-8", cwd=cwd)
        else:
            # Fall back to spawning the command directly
            if verbose:
                print("Running pexpect.spawn without shell.")
            Log.debug("Shell not found, spawning command directly")
            child = pexpect.spawn(command, encoding="utf-8", cwd=cwd)

        # Transfer control to the user, capturing output
        child.interact(output_filter=output_callback)

        # Wait for the command to finish and get the exit status
        child.close()
        output_str = output.getvalue().decode("utf-8", errors="replace")
        Log.info("Pexpect execution completed", command=command, exit_status=child.exitstatus, output_length=len(output_str))
        return child.exitstatus, output_str

    except (pexpect.ExceptionPexpect, TypeError, ValueError) as e:
        error_msg = f"Error running command {command}: {e}"
        Log.error("Pexpect execution failed", error=e, command=command)
        return 1, error_msg
