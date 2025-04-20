#!/usr/bin/env python

import subprocess
import sys

from aider.dump import dump  # noqa: F401
from treebeardhq import Log



def main():
    models = [
        "gpt-3.5-turbo-0301",
        "gpt-3.5-turbo-0613",
        # "gpt-3.5-turbo-16k-0613",
        "gpt-3.5-turbo-1106",
        # "gpt-4-0314",
        # "gpt-4-0613",
    ]
    edit_formats = [
        "diff",
        # "diff-func",
        # "whole",
        # "whole-func",
    ]

    Log.info("Starting benchmark runs", models=models, edit_formats=edit_formats)
    
    # for repeat in range(1, 2, 1):
    for model in models:
        for edit_format in edit_formats:
            # dump(model, edit_format)

            if "-func" in edit_format and "-03" in model:
                Log.debug("Skipping incompatible model and edit format combination", model=model, edit_format=edit_format)
                continue

            # if (model, edit_format) == ("gpt-3.5-turbo-16k-0613", "whole-func"):
            #    # sublist reliably hangs the API?
            #    continue

            dirname = f"rungrid-nov-{model}-{edit_format}"
            # dirname = f"rungrid-{model}-{edit_format}-repeat-{repeat}"
            Log.info("Running benchmark", model=model, edit_format=edit_format, dirname=dirname)
            run(dirname, model, edit_format)

    Log.info("Completed all benchmark runs")
    return 0


def run(dirname, model, edit_format):
    cmd = [
        "./benchmark/benchmark.py",
        dirname,
        "--model",
        model,
        "--edit-format",
        edit_format,
        "--threads",
        "10",
        "--cont",
    ]
    Log.debug("Executing benchmark command", cmd=cmd)
    print(" ".join(cmd))

    try:
        subprocess.run(cmd, check=True)
        Log.info("Benchmark subprocess completed successfully", dirname=dirname, model=model, edit_format=edit_format)
    except subprocess.CalledProcessError as e:
        Log.error("Benchmark subprocess failed", error=e, dirname=dirname, model=model, edit_format=edit_format)
        raise


if __name__ == "__main__":
    status = main()
    sys.exit(status)
