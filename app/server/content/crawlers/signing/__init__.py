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

Modules
-------
- a_bogus      : A-Bogus parameter signing for Douyin
- x_bogus      : X-Bogus parameter signing for Douyin
- wbi          : WBI signing for Bilibili
- update_check : Upstream commit auto-update checker
"""

from .a_bogus import UPSTREAM_COMMIT as _A_BOGUS_COMMIT
from .a_bogus import UPSTREAM_REPO as _UPSTREAM_REPO
from .a_bogus import sign_a_bogus
from .update_check import PINNED_COMMITS, check_upstream_updates
from .wbi import WbiSigner, get_wbi_keys
from .x_bogus import sign_x_bogus

__all__ = [
    "sign_a_bogus",
    "sign_x_bogus",
    "WbiSigner",
    "get_wbi_keys",
    "check_upstream_updates",
    "PINNED_COMMITS",
]
