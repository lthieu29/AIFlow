"""DraftWriter — serialises a JianYingDraft to the CapCut draft folder format.

CapCut stores each project as a folder containing several JSON files.
The minimum set required to open a draft is:

- ``draft_info.json``      — main timeline / materials / tracks
- ``draft_meta_info.json`` — project metadata (name, cover, etc.)

Additional files (``draft_agency_config.json``, ``draft_biz_config.json``,
``draft_settings``) are written as empty stubs so CapCut doesn't complain.

Usage::

    from server.export.capcut import JianYingDraft, DraftWriter

    draft = JianYingDraft(name="My Video")
    # ... build draft ...

    writer = DraftWriter(draft_root="C:/Users/Me/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft")
    output_dir = writer.write(draft)
    print(f"Draft written to {output_dir}")
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Optional

from .draft import JianYingDraft


class DraftWriter:
    """Writes a :class:`~.draft.JianYingDraft` to a CapCut draft folder.

    Args:
        draft_root: The root directory where CapCut stores its drafts.
            On Windows this is typically
            ``%LOCALAPPDATA%\\CapCut\\User Data\\Projects\\com.lveditor.draft``.
            If *None*, the writer will use the current working directory.
    """

    def __init__(self, draft_root: Optional[str] = None) -> None:
        self.draft_root = draft_root or os.getcwd()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(self, draft: JianYingDraft, draft_name: Optional[str] = None) -> str:
        """Write *draft* to a new sub-folder inside :attr:`draft_root`.

        Args:
            draft: The draft to serialise.
            draft_name: Folder name to use.  Defaults to ``draft.name``.

        Returns:
            Absolute path to the created draft folder.

        Raises:
            FileExistsError: If a folder with *draft_name* already exists.
        """
        name = draft_name or draft.name
        folder = os.path.join(self.draft_root, name)

        if os.path.exists(folder):
            raise FileExistsError(
                f"Draft folder already exists: {folder!r}.  "
                "Delete it first or choose a different name."
            )

        os.makedirs(folder, exist_ok=False)

        # 1. Main content file
        draft.dump(os.path.join(folder, "draft_info.json"))

        # 2. Meta info
        meta = self._build_meta(draft, name)
        with open(os.path.join(folder, "draft_meta_info.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=4)

        # 3. Stub files that CapCut expects to exist
        self._write_stub(folder, "draft_agency_config.json", {})
        self._write_stub(folder, "draft_biz_config.json", {})
        self._write_stub(folder, "draft_settings", "")

        return folder

    def write_to_dir(self, draft: JianYingDraft, output_dir: str) -> str:
        """Write *draft* directly into *output_dir* (must already exist).

        Unlike :meth:`write`, this method does **not** create a sub-folder —
        it writes the files directly into *output_dir*.  Useful when the
        caller has already created the target directory.

        Returns:
            *output_dir* (unchanged).
        """
        if not os.path.isdir(output_dir):
            raise FileNotFoundError(f"Output directory does not exist: {output_dir!r}")

        draft.dump(os.path.join(output_dir, "draft_info.json"))

        meta = self._build_meta(draft, os.path.basename(output_dir))
        with open(os.path.join(output_dir, "draft_meta_info.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=4)

        self._write_stub(output_dir, "draft_agency_config.json", {})
        self._write_stub(output_dir, "draft_biz_config.json", {})
        self._write_stub(output_dir, "draft_settings", "")

        return output_dir

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_meta(draft: JianYingDraft, folder_name: str) -> dict:
        now_ms = int(time.time() * 1000)
        return {
            "cloud_package_completed_time": "",
            "draft_cloud_capcut_purchase_info": "",
            "draft_cloud_last_action_download": False,
            "draft_cloud_materials": [],
            "draft_cloud_purchase_info": "",
            "draft_cloud_template_id": "",
            "draft_cloud_tutorial_info": "",
            "draft_cloud_videocut_purchase_info": "",
            "draft_cover": "draft_cover.jpg",
            "draft_deeplink_url": "",
            "draft_enterprise_info": {
                "draft_enterprise_extra": "",
                "draft_enterprise_id": "",
                "draft_enterprise_name": "",
                "enterprise_material": [],
            },
            "draft_fold_path": "",
            "draft_id": uuid.uuid4().hex.upper(),
            "draft_is_ai_packaging_used": False,
            "draft_is_ai_shorts": False,
            "draft_is_ai_translate": False,
            "draft_is_article_video_draft": False,
            "draft_is_from_deeplink": "false",
            "draft_is_invisible": False,
            "draft_materials": [],
            "draft_name": draft.name,
            "draft_new_version": "",
            "draft_removable_storage_device": "",
            "draft_root_path": "",
            "draft_segment_extra_info": [],
            "draft_timeline_materials_size_": 0,
            "draft_type": "",
            "tm_draft_cloud_completed": "",
            "tm_draft_cloud_modified": 0,
            "tm_draft_create": now_ms,
            "tm_draft_modified": now_ms,
            "tm_draft_removed": 0,
            "tm_duration": draft.duration,
        }

    @staticmethod
    def _write_stub(folder: str, filename: str, content: "dict | str") -> None:
        path = os.path.join(folder, filename)
        with open(path, "w", encoding="utf-8") as fh:
            if isinstance(content, dict):
                json.dump(content, fh)
            else:
                fh.write(content)
