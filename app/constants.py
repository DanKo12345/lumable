# The floor the window can shrink to. It must fit inside the work area of a
# 1366×768 screen at 150% scale (≈911×480 logical, minus the taskbar and the
# window frame) — otherwise the window opens larger than the screen and its
# bottom/right (with the primary action) fall off-screen. Content taller than
# this scrolls in the body QScrollArea; the sidebar switches to a compact mode
# (see COMPACT_SIDEBAR_HEIGHT) so its bottom status never clips.
WINDOW_MIN_WIDTH = 860
WINDOW_MIN_HEIGHT = 420

# Below this window height the sidebar can't show its full-height footer, so it
# drops the secondary status hint and shrinks the status card, keeping the
# primary connection status and all eight nav items visible.
COMPACT_SIDEBAR_HEIGHT = 580

CONTROL_HEIGHT = 44
CHIP_HEIGHT = 36

ROOT_MARGINS = (16, 12, 16, 16)

HERO_TITLE_SPACING = 2
HERO_BUTTON_HEIGHT = 40
MODE_ROW_SPACING = 8
MODE_BUTTON_MIN_WIDTH = 64
MODE_BUTTON_HEIGHT = 28

BODY_SPACING = 16
SECTION_SPACING = 16

DEVICE_CONTENT_TOP_MARGIN = 14
EFFECTS_CONTENT_TOP_MARGIN = 14
ROW_TOP_MARGIN = 2
ROW_SPACING = 10
ROW_SPACING_TIGHT = 8
ACTION_SPACING = 8

SLIDER_ROW_SPACING = 12
SLIDER_ROW_MARGINS = (0, 1, 0, 1)
SLIDER_LABEL_WIDTH = 92

STATUS_MIN_WIDTH = 132
DEVICE_ACTION_MIN_WIDTH = 124
SCAN_BUTTON_MIN_WIDTH = 152
LANGUAGE_MIN_WIDTH = 148
SAVE_BUTTON_MIN_WIDTH = 124
SCHEDULE_MISSED_WINDOW_MINUTES = 5

CRASH_LOG_MAX_FILES = 10
CRASH_LOG_MAX_AGE_DAYS = 14
FATAL_LOG_MAX_BYTES = 262_144
FATAL_LOG_TRIM_BYTES = 131_072
