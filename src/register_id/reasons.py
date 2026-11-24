"""Officer and citizen wording for audit reason codes.

Each code maps to officer text, the sentence a citizen may see, and whether
a failed face check with that code spends one of the three tries.
"""

from __future__ import annotations

# code, officer text, citizen message, uses_try
_ENTRIES: tuple[tuple[str, str, str, bool], ...] = (
    (
        "CAM-1",
        "Camera permission blocked",
        "Allow the camera in your browser settings.",
        False,
    ),
    (
        "CAM-2",
        "No camera found",
        "No camera found. Use a phone or a computer with a camera.",
        False,
    ),
    (
        "CAM-3",
        "Camera used by another app",
        "Close other apps using the camera, then try again.",
        False,
    ),
    (
        "CAM-4",
        "Page not secure (not https)",
        "Open the portal from the official link.",
        False,
    ),
    (
        "CAM-5",
        "Face tool could not load",
        "This browser cannot run the face check. Try Chrome or Safari.",
        False,
    ),
    (
        "FACE-1",
        "No face in the frame",
        "We cannot see your face. Move into the oval.",
        False,
    ),
    (
        "FACE-2",
        "More than one face",
        "Only one person in the camera, please.",
        False,
    ),
    (
        "FACE-3",
        "Frames are not the same face",
        "The scan changed person midway. Scan again.",
        True,
    ),
    (
        "IMG-1",
        "Scan data empty or broken",
        "The scan did not arrive complete. Scan again.",
        False,
    ),
    (
        "PAD-1",
        "Head did not turn left to right",
        "Turn your head slowly from left to right.",
        True,
    ),
    (
        "PAD-2",
        "Head turn too small",
        "Turn your head further to each side.",
        True,
    ),
    (
        "SESSION-1",
        "Scan session timed out",
        "Time ran out. Start the camera again.",
        False,
    ),
    (
        "SESSION-2",
        "Scan session unknown or already used",
        "Start the camera again.",
        False,
    ),
    (
        "MATCH-1",
        "Face did not match the ID",
        "This face did not match the ID.",
        True,
    ),
    (
        "MATCH-2",
        "No face stored for this ID",
        "This ID cannot be checked by face. Contact the office.",
        False,
    ),
    ("ID-1", "UIN not found", "No ID with that number.", False),
    ("ID-2", "UIN is locked", "This ID is locked. Visit the office.", False),
    (
        "ID-3",
        "UIN already exists (never overwrite)",
        "Something went wrong. Try again.",
        False,
    ),
    ("APP-1", "Details invalid", "Check the highlighted fields.", False),
    (
        "APP-2",
        "Application code expired (7 days)",
        "This application expired. Start again.",
        False,
    ),
    (
        "LIMIT-1",
        "3 tries used",
        "An officer needs to check this. Visit the office with your code.",
        False,
    ),
    (
        "LIMIT-2",
        "Too many enrolments this hour",
        "The service is busy. Try again later.",
        False,
    ),
    (
        "ACCESS-1",
        "Token missing or wrong, role not allowed",
        "You are not allowed to do this.",
        False,
    ),
    (
        "SYS-1",
        "A service we call failed",
        "Something went wrong on our side. Try again later.",
        False,
    ),
    (
        "SYS-2",
        "Our own store is down",
        "Something went wrong on our side. Try again later.",
        False,
    ),
)

REASON_CATALOG: dict[str, tuple[str, str, bool]] = {
    code: (officer, citizen, uses) for code, officer, citizen, uses in _ENTRIES
}
CODES: frozenset[str] = frozenset(REASON_CATALOG)
TRY_CODES: frozenset[str] = frozenset(
    code for code, entry in REASON_CATALOG.items() if entry[2]
)


def officer_text(code: str) -> str:
    """Officer wording for ``code``, or an empty string when the code is unknown."""
    entry = _entry(code)
    if entry is None:
        return ""
    return entry[0]


def citizen_message(code: str) -> str:
    """Citizen sentence for ``code``, or an empty string when the code is unknown."""
    entry = _entry(code)
    if entry is None:
        return ""
    return entry[1]


def uses_try(code: str) -> bool:
    """Whether a failure with this code spends a face-check try."""
    entry = _entry(code)
    if entry is None:
        return False
    return entry[2]


def rough_device(user_agent: str) -> str:
    """Short browser label. Never the raw user agent and never an IP address."""
    if not isinstance(user_agent, str):
        return "unknown"
    lowered = user_agent.lower()
    browser = _browser_name(lowered)
    if browser == "":
        return "unknown"
    if "iphone" in lowered:
        return f"{browser} on iPhone"
    if "ipad" in lowered:
        return f"{browser} on iPad"
    if "android" in lowered:
        return f"{browser} on Android"
    return browser


def _entry(code: object) -> tuple[str, str, bool] | None:
    if not isinstance(code, str):
        return None
    return REASON_CATALOG.get(code)


def _browser_name(lowered: str) -> str:
    if "edg/" in lowered or "edga/" in lowered or "edge/" in lowered:
        return "Edge"
    if "chrome/" in lowered or "crios/" in lowered:
        return "Chrome"
    if "firefox/" in lowered or "fxios/" in lowered:
        return "Firefox"
    if "safari/" in lowered:
        return "Safari"
    return ""
