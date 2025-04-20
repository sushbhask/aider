import json
import traceback
from treebeardhq import Log



def cvt(s):
    if isinstance(s, str):
        return s
    try:
        return json.dumps(s, indent=4)
    except TypeError:
        Log.debug("Could not JSON serialize value, falling back to str()", value_type=type(s).__name__)
        return str(s)


def dump(*vals):
    # http://docs.python.org/library/traceback.html
    stack = traceback.extract_stack()
    vars = stack[-2][3]

    # strip away the call to dump()
    vars = "(".join(vars.split("(")[1:])
    vars = ")".join(vars.split(")")[:-1])

    vals = [cvt(v) for v in vals]
    has_newline = sum(1 for v in vals if "\n" in v)
    
    Log.debug("Dumping variables", variable_names=vars, value_count=len(vals), has_newline=has_newline)
    
    if has_newline:
        print("%s:" % vars)
        print(", ".join(vals))
    else:
        print("%s:" % vars, ", ".join(vals))
