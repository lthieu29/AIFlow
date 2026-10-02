"""Signing modules for Douyin/TikTok/Bilibili APIs.

GPL v3 NOTICE
=============
The actual signing algorithms (A-Bogus, X-Bogus, WBI) are derived from
Douyin_TikTok_Download_API by Evil0ctal, which is licensed under the
GNU General Public License v3.0.

    https://github.com/Evil0ctal/Douyin_TikTok_Download_API

Personal use: You are free to use these stubs and the upstream GPL v3
implementation for personal, non-commercial purposes without triggering
source-disclosure obligations.

Public distribution: If you distribute a modified version publicly, you
must comply with GPL v3 (provide source, preserve notices, etc.).

ISOLATION NOTE (design.md S5)
==============================
These modules are isolated as a subprocess boundary so that the rest of
the AIFlow pipeline (MIT-licensed) is not contaminated by the GPL v3
copyleft. The signing subprocess communicates via stdin/stdout JSON only.

License summary
---------------
- a_bogus      : GPL v3 (lifted, isolated in this package)
- x_bogus      : Apache 2.0 (lifted)
- wbi          : clean-room AIFlow implementation (project license)

Modules
-------
- a_bogus      : A-Bogus parameter signing for Douyin (GPL v3, needs gmssl)
- x_bogus      : X-Bogus parameter signing for Douyin (Apache 2.0, stdlib only)
- wbi          : WBI signing for Bilibili (clean-room, httpx for key fetch)
- update_check : Upstream commit auto-update checker
- errors       : SigningError / SigningUnavailableError
"""

from .a_bogus import ABogus, sign_a_bogus
from .errors import SigningError, SigningUnavailableError
from .update_check import PINNED_COMMITS, check_upstream_updates
from .wbi import WbiSigner, get_wbi_keys
from .x_bogus import XBogus, sign_x_bogus

__all__ = [
    "sign_a_bogus",
    "sign_x_bogus",
    "ABogus",
    "XBogus",
    "WbiSigner",
    "get_wbi_keys",
    "check_upstream_updates",
    "PINNED_COMMITS",
    "SigningError",
    "SigningUnavailableError",
]
