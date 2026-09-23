"""Tests for the Zotero adapter used by the Textual UI."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.tui.zotero_adapter import ZoteroAdapter


class ZoteroAdapterTests(unittest.TestCase):
    """Verify Zotero CLI delegation and Web API PDF attachment upload."""

    def test_list_libraries_reads_user_and_group_scopes_from_local_api(self):
        """List libraries through the configured local Zotero API."""
        session = Mock()
        groups_response = Mock()
        groups_response.json.return_value = [
            {"id": 42, "data": {"name": "Reading Group"}},
        ]
        groups_response.raise_for_status.return_value = None
        session.get.return_value = groups_response

        result = ZoteroAdapter(
            api_key="secret",
            session=session,
            local_api_base="http://127.0.0.1:23119/api",
        ).list_libraries()

        self.assertEqual(
            result,
            [
                {"library_id": "0", "library_type": "user", "name": "用户库"},
                {"library_id": "42", "library_type": "group", "name": "Reading Group"},
            ],
        )
        self.assertEqual(session.get.call_args.args[0], "http://127.0.0.1:23119/api/users/0/groups")

    def test_search_items_passes_selected_library_to_local_api(self):
        """Search items with the selected explicit Zotero library scope."""
        session = Mock()
        items_response = Mock()
        items_response.json.return_value = [
            {
                "key": "ITEM123",
                "data": {
                    "title": "Paper",
                    "collections": ["COLL1"],
                    "archiveLocation": "arXiv:2508.18791",
                },
                "library": {"id": 42, "type": "group", "name": "Reading Group"},
            }
        ]
        items_response.raise_for_status.return_value = None
        collections_response = Mock()
        collections_response.json.return_value = [
            {"key": "COLL1", "data": {"name": "Inbox"}},
        ]
        collections_response.raise_for_status.return_value = None
        session.get.side_effect = [items_response, collections_response]

        result = ZoteroAdapter(api_key="secret", session=session).search_items("Paper", "42", "group")

        self.assertEqual(result[0]["item_key"], "ITEM123")
        self.assertEqual(result[0]["title"], "Paper")
        self.assertEqual(result[0]["library_id"], "42")
        self.assertEqual(result[0]["library_type"], "group")
        self.assertEqual(result[0]["library_name"], "Reading Group")
        self.assertEqual(result[0]["collection_names"], ["Inbox"])
        self.assertEqual(session.get.call_args_list[0].args[0], "http://127.0.0.1:23119/api/groups/42/items")
        self.assertEqual(session.get.call_args_list[0].kwargs["params"]["q"], "Paper")
        self.assertEqual(session.get.call_args_list[1].args[0], "http://127.0.0.1:23119/api/groups/42/collections")

    def test_match_items_by_archive_id_filters_archive_location_locally(self):
        """Auto-match returns items whose archive ID contains the current arXiv ID."""
        session = Mock()
        response = Mock()
        response.json.return_value = [
            {"key": "MATCH", "data": {"title": "Match", "archiveLocation": "arXiv:2508.18791"}},
            {"key": "MISS", "data": {"title": "Miss", "archiveLocation": "arXiv:2407.01648"}},
        ]
        response.raise_for_status.return_value = None
        session.get.return_value = response

        result = ZoteroAdapter(api_key="secret", session=session).match_items_by_archive_id(
            "2508.18791",
            "7",
            "user",
        )

        self.assertEqual([item["item_key"] for item in result], ["MATCH"])
        self.assertEqual(session.get.call_args_list[0].args[0], "http://127.0.0.1:23119/api/users/7/items")
        self.assertEqual(session.get.call_args_list[1].args[0], "http://127.0.0.1:23119/api/users/7/collections")

    def test_attach_pdf_creates_child_attachment_and_uploads_file(self):
        """Attach a translated PDF through child attachment and upload requests."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "translated.pdf"
            pdf_path.write_bytes(b"%PDF translated")

            session = Mock()
            create_response = Mock()
            create_response.json.return_value = {"successful": {"0": {"key": "ATTACH1"}}}
            create_response.raise_for_status.return_value = None
            auth_response = Mock()
            auth_response.json.return_value = {
                "url": "https://upload.example.test",
                "contentType": "multipart/form-data; boundary=x",
                "prefix": "PREFIX",
                "suffix": "SUFFIX",
                "uploadKey": "UPLOAD1",
            }
            auth_response.raise_for_status.return_value = None
            upload_response = Mock()
            upload_response.raise_for_status.return_value = None
            register_response = Mock()
            register_response.raise_for_status.return_value = None
            session.post.side_effect = [create_response, auth_response, upload_response, register_response]

            result = ZoteroAdapter(
                python_cmd=["python"],
                script_path="zotero.py",
                api_key="secret",
                session=session,
            ).attach_pdf("ITEM123", str(pdf_path), "42", "group")

        self.assertEqual(result["attachment_key"], "ATTACH1")
        self.assertEqual(result["status"], "uploaded")
        create_call = session.post.call_args_list[0]
        self.assertEqual(create_call.args[0], "https://api.zotero.org/groups/42/items")
        self.assertEqual(create_call.kwargs["json"][0]["parentItem"], "ITEM123")
        self.assertEqual(create_call.kwargs["json"][0]["linkMode"], "imported_file")
        write_token = create_call.kwargs["headers"]["Zotero-Write-Token"]
        self.assertEqual(len(write_token), 32)
        self.assertNotIn("-", write_token)
        auth_call = session.post.call_args_list[1]
        self.assertEqual(auth_call.kwargs["headers"]["If-None-Match"], "*")
        self.assertIn("md5", auth_call.kwargs["data"])
        self.assertEqual(auth_call.kwargs["data"]["filesize"], str(len(b"%PDF translated")))
        self.assertEqual(auth_call.kwargs["data"]["contentType"], "application/pdf")
        register_call = session.post.call_args_list[3]
        self.assertEqual(register_call.kwargs["headers"]["If-None-Match"], "*")
        self.assertEqual(register_call.kwargs["data"]["upload"], "UPLOAD1")

    def test_attach_pdf_returns_exists_when_zotero_reports_existing_file(self):
        """Return the existing-file status without uploading duplicate bytes."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "translated.pdf"
            pdf_path.write_bytes(b"%PDF translated")
            session = Mock()
            create_response = Mock()
            create_response.json.return_value = {"successful": {"0": {"key": "ATTACH1"}}}
            create_response.raise_for_status.return_value = None
            auth_response = Mock()
            auth_response.json.return_value = {"exists": 1}
            auth_response.raise_for_status.return_value = None
            session.post.side_effect = [create_response, auth_response]

            result = ZoteroAdapter(
                python_cmd=["python"],
                script_path="zotero.py",
                api_key="secret",
                session=session,
            ).attach_pdf("ITEM123", str(pdf_path), "42", "group")

        self.assertEqual(result, {"attachment_key": "ATTACH1", "status": "exists"})
        self.assertEqual(session.post.call_count, 2)

    def test_create_note_posts_child_note_payload(self):
        """Create a child note with the complete supplied Markdown content."""
        session = Mock()
        response = Mock()
        response.json.return_value = {"successful": {"0": {"key": "NOTE1"}}}
        response.raise_for_status.return_value = None
        session.post.return_value = response

        result = ZoteroAdapter(api_key="secret", session=session).create_note(
            "PARENT",
            "paper translated",
            "# 内容",
            "0",
            "user",
        )

        self.assertEqual(result, {"item_key": "NOTE1"})
        request = session.post.call_args
        self.assertEqual(request.args[0], "https://api.zotero.org/users/0/items")
        self.assertEqual(request.kwargs["json"][0]["itemType"], "note")
        self.assertEqual(request.kwargs["json"][0]["parentItem"], "PARENT")
        self.assertEqual(request.kwargs["json"][0]["title"], "paper translated")
        self.assertEqual(request.kwargs["json"][0]["note"], "# 内容")
        self.assertEqual(request.kwargs["json"][0]["tags"], [])
        self.assertEqual(request.kwargs["json"][0]["relations"], {})
        self.assertEqual(request.kwargs["headers"]["Zotero-API-Key"], "secret")

    def test_create_note_propagates_response_status_failure(self):
        """Propagate a failed Web API status without attempting to parse a note key."""
        session = Mock()
        response = Mock()
        failure = RuntimeError("Zotero rejected note creation")
        response.raise_for_status.side_effect = failure
        session.post.return_value = response

        with self.assertRaises(RuntimeError) as context:
            ZoteroAdapter(api_key="secret", session=session).create_note(
                "PARENT",
                "paper translated",
                "# content",
                "42",
                "group",
            )

        self.assertIs(context.exception, failure)
        response.json.assert_not_called()

    def test_create_note_rejects_response_without_note_key(self):
        """Reject a successful-looking Zotero response that omits the note key."""
        session = Mock()
        response = Mock()
        response.json.return_value = {"successful": {"0": {}}}
        response.raise_for_status.return_value = None
        session.post.return_value = response

        with self.assertRaisesRegex(RuntimeError, "note key"):
            ZoteroAdapter(api_key="secret", session=session).create_note(
                "PARENT",
                "paper translated",
                "# content",
                "42",
                "group",
            )

    def test_create_note_rejects_non_object_response(self):
        """Reject a malformed Zotero response without leaking an AttributeError."""
        session = Mock()
        response = Mock()
        response.json.return_value = []
        response.raise_for_status.return_value = None
        session.post.return_value = response

        with self.assertRaisesRegex(RuntimeError, "note key"):
            ZoteroAdapter(api_key="secret", session=session).create_note(
                "PARENT",
                "paper translated",
                "# content",
                "42",
                "group",
            )

    def test_create_note_rejects_non_object_successful_field(self):
        """Reject a malformed successful field without leaking an AttributeError."""
        session = Mock()
        response = Mock()
        response.json.return_value = {"successful": [{"key": "NOTE1"}]}
        response.raise_for_status.return_value = None
        session.post.return_value = response

        with self.assertRaisesRegex(RuntimeError, "note key"):
            ZoteroAdapter(api_key="secret", session=session).create_note(
                "PARENT",
                "paper translated",
                "# content",
                "42",
                "group",
            )


if __name__ == "__main__":
    unittest.main()
