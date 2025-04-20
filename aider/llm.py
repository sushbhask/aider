import importlib
import os
import warnings

from aider.dump import dump  # noqa: F401
from treebeardhq import Log


warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

AIDER_SITE_URL = "https://aider.chat"
AIDER_APP_NAME = "Aider"

os.environ["OR_SITE_URL"] = AIDER_SITE_URL
os.environ["OR_APP_NAME"] = AIDER_APP_NAME
os.environ["LITELLM_MODE"] = "PRODUCTION"

# `import litellm` takes 1.5 seconds, defer it!

VERBOSE = False


class LazyLiteLLM:
    _lazy_module = None

    def __getattr__(self, name):
        if name == "_lazy_module":
            return super()
        self._load_litellm()
        Log.debug("Accessing lazy-loaded litellm attribute", attribute_name=name)
        return getattr(self._lazy_module, name)

    def _load_litellm(self):
        if self._lazy_module is not None:
            return

        if VERBOSE:
            print("Loading litellm...")
            
        Log.info("Lazy-loading litellm module")
        
        self._lazy_module = importlib.import_module("litellm")

        self._lazy_module.suppress_debug_info = True
        self._lazy_module.set_verbose = False
        self._lazy_module.drop_params = True
        self._lazy_module._logging._disable_debugging()
        
        Log.debug("Configured litellm module settings", 
                  suppress_debug_info=self._lazy_module.suppress_debug_info,
                  set_verbose=self._lazy_module.set_verbose,
                  drop_params=self._lazy_module.drop_params)


litellm = LazyLiteLLM()

__all__ = [litellm]
