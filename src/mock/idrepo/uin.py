"""
UINs that pass MOSIP's UIN validator, so the mock generator's numbers are accepted by a real
MOSIP ID Repository (1.2.0.1) as well as by this mock.

Rules are MOSIP's defaults (mosip-config application-default.properties, mosip.kernel.uin.*) and
the checks in kernel-idvalidator-uin UinValidatorImpl; checksum tables are kernel-core ChecksumUtils:

* 10 digits, not starting with 0 or 1, last digit is the Verhoeff checksum
* no restricted numbers (786, 666)
* no ascending or descending run of 3 (sequence-limit 3)
* no digit repeated within 2 places (repeating-limit 2, regex (\\d)\\d{0,1}\\1)
* no repeated block of 2 or more digits (repeating-block-limit 2, regex (\\d{2,}).*?\\1)
* no 3 of 2, 4, 6, 8 in a row (conjugative-even-digits-limit 3, regex [2468]{3})
* first 5 digits differ from the last 5 and from the last 5 reversed
"""

from __future__ import annotations

import re
import secrets

_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5), (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7), (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3), (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4), (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7), (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)

_SEQ_ASC = "0123456789"
_SEQ_DESC = "9876543210"
_REPEATING = re.compile(r"(\d)\d{0,1}\1")
_REPEATING_BLOCK = re.compile(r"(\d{2,}).*?\1")
_EVEN_RUN = re.compile(r"[2468]{3}")
_RESTRICTED = ("786", "666")


def checksum_digit(number: str) -> str:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def checksum_valid(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def is_valid_uin(uin: str) -> bool:
    if not re.fullmatch(r"[2-9]\d{9}", uin or ""):
        return False
    if any(uin[i:i + 3] in _SEQ_ASC or uin[i:i + 3] in _SEQ_DESC for i in range(len(uin) - 2)):
        return False
    if _REPEATING.search(uin) or _REPEATING_BLOCK.search(uin) or _EVEN_RUN.search(uin):
        return False
    if any(number in uin for number in _RESTRICTED):
        return False
    if not checksum_valid(uin):
        return False
    return uin[:5] != uin[5:] and uin[:5] != uin[5:][::-1]


def new_uin() -> str:
    while True:
        body = str(secrets.choice(range(2, 10))) + "".join(str(secrets.randbelow(10)) for _ in range(8))
        uin = body + checksum_digit(body)
        if is_valid_uin(uin):
            return uin
