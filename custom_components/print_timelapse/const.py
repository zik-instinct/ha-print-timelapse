"""Constants for the Print Timelapse Archive integration."""

from typing import Final

DOMAIN: Final = "print_timelapse"

# Config entry data / options
CONF_CAMERA_ENTITY: Final = "camera_entity"
CONF_STATUS_ENTITY: Final = "status_entity"
CONF_PRINTING_STATES: Final = "printing_states"
CONF_CAPTURE_INTERVAL: Final = "capture_interval"
CONF_JOB_NAME_ATTRIBUTE: Final = "job_name_attribute"
CONF_SIDEBAR_TITLE: Final = "sidebar_title"
CONF_KEEP_FRAMES: Final = "keep_frames"
CONF_FPS: Final = "fps"
CONF_RESERVE_GB: Final = "reserve_gb"

DEFAULT_PRINTING_STATES: Final = "printing"
DEFAULT_CAPTURE_INTERVAL: Final = 60  # seconds
DEFAULT_SIDEBAR_TITLE: Final = "Timelapses"
DEFAULT_KEEP_FRAMES: Final = False
DEFAULT_FPS: Final = 30
DEFAULT_RESERVE_GB: Final = 2

MIN_CAPTURE_INTERVAL: Final = 5
MAX_CAPTURE_INTERVAL: Final = 3600

RESOLUTIONS: Final = ("720p", "1080p")
RESOLUTION_HEIGHT: Final = {"720p": 720, "1080p": 1080}

# Archive layout inside the local media directory
MEDIA_DIR_NAME: Final = "print_timelapse_archive"
INDEX_FILE: Final = "index.json"
DETAILS_FILE: Final = "details.json"
NAMES_FILE: Final = "names.json"
ASSEMBLED_MARKER: Final = "assembled.json"
SCHEMA_VERSION: Final = 1

# Panels / static
PANEL_URL_PATH: Final = "print-timelapse"
PANEL_ICON: Final = "mdi:video-vintage"
PANEL_WEBCOMPONENT: Final = "print-timelapse-panel"
STATIC_URL_PATH: Final = f"/{DOMAIN}_static"
PANEL_JS_FILE: Final = "print-timelapse-panel.js"

STORAGE_VERSION: Final = 1

SERVICE_REBUILD_INDEX: Final = "rebuild_index"

SIGNAL_ARCHIVE_UPDATED: Final = f"{DOMAIN}_archive_updated_{{}}"

ATTR_SCHEMA: Final = "schema"

WS_TYPE_LIST: Final = f"{DOMAIN}/list"
WS_TYPE_JOB: Final = f"{DOMAIN}/job"

COVERAGE_NOTE: Final = (
    "Interval captures, not layer-end images. First and last are saved-image "
    "timestamps, not verified print start/end. An assembled video does not "
    "establish print success or complete coverage."
)

RETENTION_NOTE: Final = (
    "Archived videos and one preview frame are retained independently of the "
    "rolling capture folders. No automatic archive deletion. This archive lives "
    "on your Home Assistant storage and is not an off-site backup."
)
