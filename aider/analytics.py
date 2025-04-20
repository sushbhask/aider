import json
import platform
import sys
import time
import uuid
from pathlib import Path

from mixpanel import MixpanelException
from posthog import Posthog

from aider import __version__
from aider.dump import dump  # noqa: F401
from aider.models import model_info_manager
from treebeardhq import Log


PERCENT = 10


def compute_hex_threshold(percent):
    """Convert percentage to 6-digit hex threshold.

    Args:
        percent: Percentage threshold (0-100)

    Returns:
        str: 6-digit hex threshold
    """
    Log.debug("Computing hex threshold", percent=percent)
    threshold = format(int(0xFFFFFF * percent / 100), "06x")
    Log.debug("Computed hex threshold", percent=percent, threshold=threshold)
    return threshold


def is_uuid_in_percentage(uuid_str, percent):
    """Check if a UUID string falls within the first X percent of the UUID space.

    Args:
        uuid_str: UUID string to test
        percent: Percentage threshold (0-100)

    Returns:
        bool: True if UUID falls within the first X percent
    """
    Log.debug("Checking if UUID in percentage", uuid_str=uuid_str, percent=percent)
    
    if not (0 <= percent <= 100):
        Log.error("Invalid percentage value", percent=percent)
        raise ValueError("Percentage must be between 0 and 100")

    if not uuid_str:
        Log.debug("Empty UUID string, returning False", uuid_str=uuid_str)
        return False

    # Convert percentage to hex threshold (1% = "04...", 10% = "1a...", etc)
    # Using first 6 hex digits
    if percent == 0:
        Log.debug("Percentage is 0, returning False", percent=percent)
        return False

    threshold = compute_hex_threshold(percent)
    result = uuid_str[:6] <= threshold
    Log.debug("UUID percentage check complete", uuid_str=uuid_str, first_six=uuid_str[:6], threshold=threshold, result=result)
    return result

mixpanel_project_token = "6da9a43058a5d1b9f3353153921fb04d"
posthog_project_api_key = "phc_99T7muzafUMMZX15H8XePbMSreEUzahHbtWjy3l5Qbv"
posthog_host = "https://us.i.posthog.com"


class Analytics:
    # providers
    mp = None
    ph = None

    # saved
    user_id = None
    permanently_disable = None
    asked_opt_in = None

    # ephemeral
    logfile = None

    def __init__(self, logfile=None, permanently_disable=False):
        self.logfile = logfile
        self.get_or_create_uuid()

        if self.permanently_disable or permanently_disable or not self.asked_opt_in:
            self.disable(permanently_disable)

    def enable(self):
        Log.debug("Enabling analytics", user_id=self.user_id, permanently_disable=self.permanently_disable, asked_opt_in=self.asked_opt_in)
        
        if not self.user_id:
            Log.debug("No user ID found, disabling analytics")
            self.disable(False)
            return

        if self.permanently_disable:
            Log.debug("Analytics permanently disabled, keeping disabled")
            self.disable(True)
            return

        if not self.asked_opt_in:
            Log.debug("User not asked for opt-in, disabling analytics")
            self.disable(False)
            return

        # self.mp = Mixpanel(mixpanel_project_token)
        self.ph = Posthog(
            project_api_key=posthog_project_api_key,
            host=posthog_host,
            on_error=self.posthog_error,
            enable_exception_autocapture=True,
            super_properties=self.get_system_info(),  # Add system info to all events
        )
        Log.info("Analytics enabled", user_id=self.user_id)

    def disable(self, permanently):
        Log.debug("Disabling analytics", permanently=permanently, user_id=self.user_id)
        self.mp = None
        self.ph = None

        if permanently:
            self.asked_opt_in = True
            self.permanently_disable = True
            self.save_data()
            Log.info("Analytics permanently disabled", user_id=self.user_id)

    def need_to_ask(self, args_analytics):
        Log.debug("Checking if need to ask for analytics consent", args_analytics=args_analytics, asked_opt_in=self.asked_opt_in, permanently_disable=self.permanently_disable)
        
        if args_analytics is False:
            Log.debug("Analytics explicitly disabled via args, no need to ask")
            return False

        could_ask = not self.asked_opt_in and not self.permanently_disable
        if not could_ask:
            Log.debug("Already asked or permanently disabled, no need to ask")
            return False

        if args_analytics is True:
            Log.debug("Analytics explicitly enabled via args, need to ask")
            return True

        assert args_analytics is None, args_analytics

        if not self.user_id:
            Log.debug("No user ID, no need to ask")
            return False

        result = is_uuid_in_percentage(self.user_id, PERCENT)
        Log.debug("Determined if need to ask based on UUID percentage", result=result, user_id=self.user_id, percent=PERCENT)
        return result

    def get_data_file_path(self):
        try:
            data_file = Path.home() / ".aider" / "analytics.json"
            data_file.parent.mkdir(parents=True, exist_ok=True)
            return data_file
        except OSError as e:
            # If we can't create/access the directory, just disable analytics
            Log.error("Unable to create/access analytics directory", error=e)
            self.disable(permanently=False)
            return None

    def get_or_create_uuid(self):
        Log.debug("Getting or creating UUID")
        self.load_data()
        if self.user_id:
            Log.debug("Existing UUID found", user_id=self.user_id)
            return

        self.user_id = str(uuid.uuid4())
        Log.debug("Created new UUID", user_id=self.user_id)
        self.save_data()

    def load_data(self):
        Log.debug("Loading analytics data")
        data_file = self.get_data_file_path()
        if not data_file:
            Log.debug("No data file path available")
            return

        if data_file.exists():
            try:
                data = json.loads(data_file.read_text())
                self.permanently_disable = data.get("permanently_disable")
                self.user_id = data.get("uuid")
                self.asked_opt_in = data.get("asked_opt_in", False)
                Log.debug("Loaded analytics data", user_id=self.user_id, permanently_disable=self.permanently_disable, asked_opt_in=self.asked_opt_in)
            except (json.decoder.JSONDecodeError, OSError) as e:
                Log.error("Error loading analytics data", error=e)
                self.disable(permanently=False)

    def save_data(self):
        Log.debug("Saving analytics data", user_id=self.user_id, permanently_disable=self.permanently_disable, asked_opt_in=self.asked_opt_in)
        data_file = self.get_data_file_path()
        if not data_file:
            Log.debug("No data file path available")
            return

        data = dict(
            uuid=self.user_id,
            permanently_disable=self.permanently_disable,
            asked_opt_in=self.asked_opt_in,
        )

        try:
            data_file.write_text(json.dumps(data, indent=4))
            Log.debug("Analytics data saved successfully")
        except OSError as e:
            # If we can't write the file, just disable analytics
            Log.error("Error saving analytics data", error=e)
            self.disable(permanently=False)

    def get_system_info(self):
        Log.debug("Getting system info")
        system_info = {
            "python_version": sys.version.split()[0],
            "os_platform": platform.system(),
            "os_release": platform.release(),
            "machine": platform.machine(),
            "aider_version": __version__,
        }
        Log.debug("System info retrieved", system_info=system_info)
        return system_info

    def _redact_model_name(self, model):
        if not model:
            Log.debug("No model to redact")
            return None

        info = model_info_manager.get_model_from_cached_json_db(model.name)
        if info:
            Log.debug("Model in cached DB, returning full name", model_name=model.name)
            return model.name
        elif "/" in model.name:
            redacted_name = model.name.split("/")[0] + "/REDACTED"
            Log.debug("Model not in cached DB, redacting name", original_name=model.name, redacted_name=redacted_name)
            return redacted_name
        return None

    def posthog_error(self):
        """disable posthog if we get an error"""
        Log.error("PostHog error occurred, disabling PostHog")
        print("X" * 100)
        # https://github.com/PostHog/posthog-python/blob/9e1bb8c58afaa229da24c4fb576c08bb88a75752/posthog/consumer.py#L86
        # https://github.com/Aider-AI/aider/issues/2532
        self.ph = None

    def event(self, event_name, main_model=None, **kwargs):
        Log.debug("Recording analytics event", event_name=event_name)
        if not self.mp and not self.ph and not self.logfile:
            Log.debug("No analytics providers configured, skipping event")
            return

        properties = {}

        if main_model:
            properties["main_model"] = self._redact_model_name(main_model)
            properties["weak_model"] = self._redact_model_name(main_model.weak_model)
            properties["editor_model"] = self._redact_model_name(main_model.editor_model)

        properties.update(kwargs)

        # Handle numeric values
        for key, value in properties.items():
            if isinstance(value, (int, float)):
                properties[key] = value
            else:
                properties[key] = str(value)

        if self.mp:
            try:
                self.mp.track(self.user_id, event_name, dict(properties))
                Log.debug("Event sent to Mixpanel", event_name=event_name)
            except MixpanelException as e:
                Log.error("Error sending event to Mixpanel", error=e)
                self.mp = None  # Disable mixpanel on connection errors

        if self.ph:
            self.ph.capture(self.user_id, event_name, dict(properties))
            Log.debug("Event sent to PostHog", event_name=event_name)

        if self.logfile:
            log_entry = {
                "event": event_name,
                "properties": properties,
                "user_id": self.user_id,
                "time": int(time.time()),
            }
            try:
                with open(self.logfile, "a") as f:
                    json.dump(log_entry, f)
                    f.write("\n")
                Log.debug("Event written to logfile", event_name=event_name, logfile=self.logfile)
            except OSError as e:
                Log.error("Error writing event to logfile", error=e, logfile=self.logfile)
                pass  # Ignore OS errors when writing to logfile


if __name__ == "__main__":
    dump(compute_hex_threshold(PERCENT))
