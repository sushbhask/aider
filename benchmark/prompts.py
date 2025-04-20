
from treebeardhq import Log
instructions_addendum = """
####

Use the above instructions to modify the supplied files: {file_list}
Don't change the names of existing functions or classes, as they may be referenced from other code like unit tests, etc.
Only use standard libraries, don't suggest installing any packages.
"""  # noqa: E501

Log.debug("Defined instructions addendum template", file_list_placeholder="{file_list}")

test_failures = """
####

See the testing errors above.
The tests are correct, don't try and change them.
Fix the code in {file_list} to resolve the errors.
"""

Log.debug("Defined test failures template", file_list_placeholder="{file_list}")
