"""Make a UIN that passes MOSIP's UIN validator (kernel UinValidatorImpl, 1.2.0.1 rules from mosip-config).

The real kernel idgenerator only hands out such numbers. register-id's mock generator returns plain random
10-digit numbers, which the real ID Repository rejects with IDR-IDC-002 "Invalid Input Parameter - UIN".

Rules (application-default.properties, mosip.kernel.uin.*):
  length 10, digits only, does not start with 0 or 1, last digit = Verhoeff checksum,
  no restricted numbers (786, 666), no ascending/descending run of 3 (sequence-limit),
  a digit does not repeat within 2 places (repeating-limit), no repeated 2-digit block (repeating-block-limit),
  first 5 digits are not the last 5 reversed (reverse-digits-limit) or equal to them (digits-limit),
  no 3 of the digits 2,4,6,8 in a row (conjugative-even-digits-limit, regex [2468]{3}).
Checksum tables copied from kernel-core ChecksumUtils (v1.2.0.1).
"""

import random
import re

_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
      [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
      [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
      [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
      [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
      [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_digit(number: str) -> str:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def is_valid(uin: str) -> bool:
    if not re.fullmatch(r"[2-9][0-9]{9}", uin):
        return False
    if verhoeff_digit(uin[:-1]) != uin[-1]:
        return False
    if "786" in uin or "666" in uin:
        return False
    d = [int(c) for c in uin]
    for i in range(len(d) - 2):
        if d[i + 1] - d[i] == d[i + 2] - d[i + 1] in (1, -1):
            return False
        if all(x in (2, 4, 6, 8) for x in d[i:i + 3]):
            return False
    if re.search(r"(\d)\d{0,1}\1", uin):
        return False
    if re.search(r"(\d{2}).*\1", uin):
        return False
    if uin[:5] == uin[5:] or uin[:5] == uin[5:][::-1]:
        return False
    return True


def new_uin() -> str:
    while True:
        body = str(random.randint(2, 9)) + "".join(str(random.randint(0, 9)) for _ in range(8))
        uin = body + verhoeff_digit(body)
        if is_valid(uin):
            return uin


if __name__ == "__main__":
    print(new_uin())
