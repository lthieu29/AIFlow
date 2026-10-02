"""X-Bogus signing module for Douyin web API requests.

LICENSE NOTICE (Apache 2.0)
===========================
The ``XBogus`` algorithm below is from Douyin_TikTok_Download_API by Evil0ctal,
licensed under the **Apache License 2.0** (NOT GPL — unlike a_bogus.py).

    UPSTREAM_REPO : https://github.com/Evil0ctal/Douyin_TikTok_Download_API

Purpose
-------
Generate the ``X-Bogus`` query-parameter signature used by some Douyin web API
endpoints. It is computed from the canonical query string plus the User-Agent
using multiple rounds of MD5 and RC4. Uses only the Python standard library
(``hashlib``, ``base64``) — no optional dependencies.

A-Bogus (see ``a_bogus.py``) is the newer/primary signature; X-Bogus is kept as
a complementary option for endpoints that still accept it.
"""

from __future__ import annotations

import base64
import hashlib
import time

from .a_bogus import UPSTREAM_COMMIT, UPSTREAM_REPO  # shared upstream reference

__all__ = ["XBogus", "sign_x_bogus", "UPSTREAM_REPO", "UPSTREAM_COMMIT"]

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
)


class XBogus:
    """Pure-python X-Bogus signature generator (Apache 2.0, see module docstring)."""

    def __init__(self, user_agent: str | None = None) -> None:
        # fmt: off
        self.Array = [
            None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, None, None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None, None, None, None, None, 10, 11, 12, 13, 14, 15,
        ]
        # fmt: on
        self.character = "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe="
        self.ua_key = b"\x00\x01\x0c"
        self.user_agent = user_agent if user_agent else _DEFAULT_UA

    def md5_str_to_array(self, md5_str):
        if isinstance(md5_str, str) and len(md5_str) > 32:
            return [ord(char) for char in md5_str]
        array = []
        idx = 0
        while idx < len(md5_str):
            array.append(
                (self.Array[ord(md5_str[idx])] << 4) | self.Array[ord(md5_str[idx + 1])]
            )
            idx += 2
        return array

    def md5_encrypt(self, url_path):
        return self.md5_str_to_array(self.md5(self.md5_str_to_array(self.md5(url_path))))

    def md5(self, input_data) -> str:
        if isinstance(input_data, str):
            array = self.md5_str_to_array(input_data)
        elif isinstance(input_data, list):
            array = input_data
        else:
            raise ValueError("Invalid input type. Expected str or list.")
        md5_hash = hashlib.md5()
        md5_hash.update(bytes(array))
        return md5_hash.hexdigest()

    def encoding_conversion(self, a, b, c, e, d, t, f, r, n, o, i, _, x, u, s, l, v, h, p):
        y = [a, int(i), b, _, c, x, e, u, d, s, t, l, f, v, r, h, n, p, o]
        return bytes(y).decode("ISO-8859-1")

    def encoding_conversion2(self, a, b, c) -> str:
        return chr(a) + chr(b) + c

    def rc4_encrypt(self, key, data) -> bytearray:
        S = list(range(256))
        j = 0
        for i in range(256):
            j = (j + S[i] + key[i % len(key)]) % 256
            S[i], S[j] = S[j], S[i]
        i = j = 0
        out = bytearray()
        for byte in data:
            i = (i + 1) % 256
            j = (j + S[i]) % 256
            S[i], S[j] = S[j], S[i]
            out.append(byte ^ S[(S[i] + S[j]) % 256])
        return out

    def calculation(self, a1, a2, a3) -> str:
        x3 = ((a1 & 255) << 16) | ((a2 & 255) << 8) | a3
        return (
            self.character[(x3 & 16515072) >> 18]
            + self.character[(x3 & 258048) >> 12]
            + self.character[(x3 & 4032) >> 6]
            + self.character[x3 & 63]
        )

    def getXBogus(self, url_path: str):
        """Return ``(url_with_xbogus, xbogus_value, user_agent)``."""
        array1 = self.md5_str_to_array(
            self.md5(
                base64.b64encode(
                    self.rc4_encrypt(self.ua_key, self.user_agent.encode("ISO-8859-1"))
                ).decode("ISO-8859-1")
            )
        )
        array2 = self.md5_str_to_array(
            self.md5(self.md5_str_to_array("d41d8cd98f00b204e9800998ecf8427e"))
        )
        url_path_array = self.md5_encrypt(url_path)

        timer = int(time.time())
        ct = 536919696
        # fmt: off
        new_array = [
            64, 0.00390625, 1, 12,
            url_path_array[14], url_path_array[15], array2[14], array2[15], array1[14], array1[15],
            timer >> 24 & 255, timer >> 16 & 255, timer >> 8 & 255, timer & 255,
            ct >> 24 & 255, ct >> 16 & 255, ct >> 8 & 255, ct & 255,
        ]
        # fmt: on
        xor_result = new_array[0]
        for i in range(1, len(new_array)):
            b = new_array[i]
            if isinstance(b, float):
                b = int(b)
            xor_result ^= b
        new_array.append(xor_result)

        array3, array4 = [], []
        idx = 0
        while idx < len(new_array):
            array3.append(new_array[idx])
            if idx + 1 < len(new_array):
                array4.append(new_array[idx + 1])
            idx += 2
        merge_array = array3 + array4

        garbled_code = self.encoding_conversion2(
            2,
            255,
            self.rc4_encrypt(
                "\u00ff".encode("ISO-8859-1"),
                self.encoding_conversion(*merge_array).encode("ISO-8859-1"),
            ).decode("ISO-8859-1"),
        )

        xb_ = ""
        idx = 0
        while idx < len(garbled_code):
            xb_ += self.calculation(
                ord(garbled_code[idx]),
                ord(garbled_code[idx + 1]),
                ord(garbled_code[idx + 2]),
            )
            idx += 3
        params = f"{url_path}&X-Bogus={xb_}"
        return params, xb_, self.user_agent


# ─── Public API ───────────────────────────────────────────────────────────────


def sign_x_bogus(params: dict, user_agent: str = _DEFAULT_UA) -> str:
    """Compute the ``X-Bogus`` signature value for a Douyin request.

    Args:
        params:     Query parameters dict (canonical order preserved by caller).
        user_agent: User-Agent string sent with the request.

    Returns:
        The X-Bogus signature value (non-empty string).

    Raises:
        ValueError: If *params* is not a dict.
    """
    if not isinstance(params, dict):
        raise ValueError("params must be a dict")
    param_str = "&".join(f"{k}={v}" for k, v in params.items())
    _, xb_value, _ = XBogus(user_agent).getXBogus(param_str)
    return xb_value
