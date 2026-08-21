"""Private ELO test opponents for development.

These records are intentionally isolated behind PRIME_ELO_DEV_MODE and must
never be exposed to normal users. They make it possible to test the ELO arena
with a single Telegram account.
"""

import os

DEV_MODE = os.environ.get("PRIME_ELO_DEV_MODE", "0") == "1"

TEST_OPPONENTS = [
    {"id": "dev_elo_980", "name": "PRIME TEST 980", "elo": 980, "prime_score": 38},
    {"id": "dev_elo_1100", "name": "PRIME TEST 1100", "elo": 1100, "prime_score": 52},
    {"id": "dev_elo_1250", "name": "PRIME TEST 1250", "elo": 1250, "prime_score": 64},
    {"id": "dev_elo_1450", "name": "PRIME TEST 1450", "elo": 1450, "prime_score": 76},
    {"id": "dev_elo_1650", "name": "PRIME TEST 1650", "elo": 1650, "prime_score": 88},
]


def get_opponents():
    return TEST_OPPONENTS[:] if DEV_MODE else []
