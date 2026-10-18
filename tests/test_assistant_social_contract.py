"""Local-only regression checks for the voice and Instagram reference flow."""

from __future__ import annotations

import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TEMP = tempfile.TemporaryDirectory(prefix="artha-assistant-contract-")
os.environ["SHOPPINGHELP_DB_PATH"] = str(Path(_TEMP.name) / "app.sqlite3")
os.environ["SHOPPINGHELP_PRIVATE_DIR"] = str(Path(_TEMP.name) / "private")

from backend import conversation, server, social  # noqa: E402


class AssistantSocialContracts(unittest.TestCase):
    def _handler(self, path: str, payload: dict | None = None) -> server.Handler:
        handler = server.Handler.__new__(server.Handler)
        handler.path = path
        handler.client_address = ("127.0.0.1", 12345)
        handler._read_json = Mock(return_value=payload or {})
        handler._assistant_user = Mock(return_value=("voice-contract-user", "Arjeet"))
        handler._send = Mock()
        return handler

    def test_friend_style_sentence_resolves_to_named_instagram_friend(self) -> None:
        resolution = {
            "success": False,
            "status": "needs_handle",
            "friend_name": "Paras",
            "message": "What is Paras's Instagram handle?",
        }
        with patch.object(conversation, "resolve_instagram_reference", return_value=resolution) as resolve:
            result = conversation.process_conversation_turn(
                "voice-contract-user", "I like my friend Paras's dressing sense"
            )

        self.assertEqual(result["state"]["friend_name"], "Paras")
        self.assertTrue(result["state"]["awaiting_instagram_handle"])
        resolve.assert_called_once_with(
            "voice-contract-user",
            "I like my friend Paras's dressing sense",
            friend_name="Paras",
            max_posts=5,
        )

    def test_unknown_session_id_cannot_overwrite_another_users_session(self) -> None:
        original = conversation.db.save_conversation_session(
            "session-owned-by-someone-else", "other-user", {"marker": "keep"}, []
        )

        replacement = conversation.get_or_start_session(
            "voice-contract-user", session_id="session-owned-by-someone-else"
        )

        self.assertNotEqual(replacement["id"], original["id"])
        self.assertEqual(
            conversation.db.get_conversation_session(original["id"], "other-user")["state"],
            {"marker": "keep"},
        )

    def test_assistant_route_uses_service_text_contract(self) -> None:
        handler = self._handler(
            "/api/assistant/converse",
            {"session_id": "session-1", "message": "Find a shirt"},
        )
        with patch.object(server, "process_conversation_turn", return_value={"reply": "What size?"}) as process:
            server.Handler.do_POST(handler)

        process.assert_called_once_with(
            user_id="voice-contract-user",
            text="Find a shirt",
            session_id="session-1",
            reference_image=None,
            reference_url="",
        )
        handler._send.assert_called_once_with(200, {"reply": "What size?"})

    def test_confirm_route_passes_supported_item_hint(self) -> None:
        handler = self._handler(
            "/api/assistant/confirm-reference",
            {"session_id": "session-1", "reference_id": "igref-1", "item_hint": "linen shirt"},
        )
        with patch.object(server, "confirm_instagram_post_and_search", return_value={"reply": "Done"}) as confirm:
            server.Handler.do_POST(handler)

        confirm.assert_called_once_with(
            user_id="voice-contract-user",
            session_id="session-1",
            reference_id="igref-1",
            item_hint="linen shirt",
        )
        handler._send.assert_called_once_with(200, {"reply": "Done"})

    def test_screenshot_route_looks_up_reference_for_current_owner_only(self) -> None:
        handler = self._handler("/api/social/screenshots/igref-other-user")
        with patch.object(server, "screenshot_file_for_reference", return_value=None) as lookup:
            server.Handler.do_GET(handler)

        lookup.assert_called_once_with("igref-other-user", "voice-contract-user")
        self.assertEqual(handler._send.call_args.args[0], 404)

    def test_upload_accepts_data_url_and_keeps_matching_image_extension(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="artha-instagram-upload-")
        self.addCleanup(directory.cleanup)
        with patch.object(social, "_SCREENSHOT_STORAGE_DIR", Path(directory.name)), patch.object(
            social.db, "save_instagram_reference", side_effect=lambda record: record
        ):
            saved = social.save_uploaded_instagram_reference(
                "voice-contract-user",
                image_base64=f"data:image/png;base64,{base64.b64encode(b'png-data').decode()}",
                source_url="",
                friend_name="Paras",
            )

        path = Path(saved["screenshot_path"])
        self.assertEqual(path.suffix, ".png")
        self.assertEqual(path.read_bytes(), b"png-data")
        self.assertTrue(saved["screenshot_preview"].startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()
