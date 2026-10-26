"""Tests for the Zotero adapter used by the Textual UI."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.tui.zotero_adapter import ZoteroAdapter


class ZoteroAdapterTests(unittest.TestCase):
    """Verify Zotero CLI delegation and Web API PDF attachment upload."""

    def test_local_write_capability_requires_server_identity(self):
        """旧版只读本地 API 不应被当成可写接口。"""
        session = Mock()
        session.get.return_value.headers = {"Zotero-API-Version": "3"}
        adapter = ZoteroAdapter(session=session)

        with self.assertRaisesRegex(RuntimeError, "不支持本地写入"):
            adapter.check_local_write_support()

        session.get.return_value.headers = {
            "Zotero-API-Version": "3", "Zotero-Server-ID": "SERVER1"
        }
        adapter.check_local_write_support()

    def test_attach_pdf_locally_authorizes_and_uploads(self):
        """本地模式使用本地写入凭据和附件上传接口。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "translated.pdf"
            pdf_path.write_bytes(b"%PDF translated")
            session = Mock()
            session.get.return_value.headers = {
                "Zotero-API-Version": "3", "Zotero-Server-ID": "SERVER1"
            }
            auth = Mock()
            auth.json.return_value = {"key": "LOCALKEY", "remember": True}
            create = Mock()
            create.json.return_value = {"successful": {"0": {"key": "ATTACH1"}}}
            upload_auth = Mock()
            upload_auth.json.return_value = {
                "url": "http://127.0.0.1:23119/api/local/uploads/UPLOAD1",
                "contentType": "application/pdf", "prefix": "", "suffix": "", "uploadKey": "UPLOAD1"
            }
            session.post.side_effect = [auth, create, upload_auth, Mock(), Mock()]

            with patch("keyring.get_password", return_value=None), patch("keyring.set_password"):
                result = ZoteroAdapter(session=session).attach_pdf_local(
                    "ITEM1", str(pdf_path), "0", "user"
                )

        self.assertEqual(result, {"attachment_key": "ATTACH1", "status": "uploaded"})
        self.assertEqual(session.post.call_args_list[0].args[0], "http://127.0.0.1:23119/api/local/authorize")
        self.assertEqual(session.post.call_args_list[0].kwargs["headers"]["Zotero-Server-ID"], "SERVER1")
        self.assertEqual(session.post.call_args_list[1].kwargs["headers"]["Zotero-Server-ID"], "SERVER1")
        self.assertEqual(session.post.call_args_list[1].kwargs["headers"]["Zotero-API-Key"], "LOCALKEY")
        self.assertEqual(session.post.call_args_list[1].kwargs["json"][0]["parentItem"], "ITEM1")
        self.assertEqual(session.post.call_args_list[2].args[0], "http://127.0.0.1:23119/api/users/0/items/ATTACH1/file")
        self.assertEqual(session.post.call_args_list[3].kwargs["data"], b"%PDF translated")
        self.assertEqual(session.post.call_args_list[4].kwargs["data"], {"upload": "UPLOAD1"})

    def test_local_write_reauthorizes_after_one_time_key_expires(self):
        """一次性 key 被消费后重新授权并重试写请求。"""
        session = Mock()
        expired = Mock(status_code=401)
        accepted = Mock(status_code=204)
        authorization = Mock()
        authorization.json.return_value = {"key": "NEWKEY"}
        session.post.side_effect = [expired, authorization, accepted]
        adapter = ZoteroAdapter(session=session)
        headers = {"Zotero-API-Key": "OLDKEY", "Zotero-Server-ID": "SERVER1"}

        with patch("keyring.get_password", return_value=None), patch("keyring.delete_password"):
            adapter._post_local_write("http://127.0.0.1:23119/api/users/0/items", headers=headers)

        self.assertEqual(session.post.call_args_list[1].kwargs["headers"]["Zotero-Server-ID"], "SERVER1")
        self.assertEqual(session.post.call_args_list[2].kwargs["headers"]["Zotero-API-Key"], "NEWKEY")

    def test_remembered_local_key_is_reused_by_new_adapter(self):
        """用户选择始终允许后，下次导入直接使用系统凭据。"""
        stored: dict[tuple[str, str], str] = {}
        session = Mock()
        authorization = Mock()
        authorization.json.return_value = {"key": "PERSISTENT", "remember": True}
        session.post.return_value = authorization
        with patch("keyring.get_password", side_effect=lambda service, account: stored.get((service, account))), patch(
            "keyring.set_password", side_effect=lambda service, account, key: stored.__setitem__((service, account), key)
        ):
            first = ZoteroAdapter(session=session)._local_api_key("SERVER1")
            second = ZoteroAdapter(session=session)._local_api_key("SERVER1")

        self.assertEqual((first, second), ("PERSISTENT", "PERSISTENT"))
        self.assertEqual(session.post.call_count, 1)
        self.assertIn("PERSISTENT", stored.values())

    def test_one_time_local_key_is_not_saved(self):
        """一次允许产生的 key 不保存到系统凭据。"""
        session = Mock()
        session.post.return_value.json.return_value = {"key": "ONETIME", "remember": False}
        with patch("keyring.get_password", return_value=None), patch("keyring.set_password") as save:
            key = ZoteroAdapter(session=session)._local_api_key("SERVER1")

        self.assertEqual(key, "ONETIME")
        save.assert_not_called()

    def test_unauthorized_stored_key_is_removed_before_reauthorization(self):
        """401 清除被 Zotero 撤销的持久 key 后再次请求授权。"""
        session = Mock()
        denied = Mock(status_code=401)
        authorization = Mock()
        authorization.json.return_value = {"key": "NEWKEY", "remember": True}
        accepted = Mock(status_code=204)
        session.post.side_effect = [denied, authorization, accepted]
        headers = {"Zotero-API-Key": "OLDKEY", "Zotero-Server-ID": "SERVER1"}
        with patch("keyring.get_password", return_value="OLDKEY"), patch("keyring.delete_password") as delete, patch("keyring.set_password") as save:
            ZoteroAdapter(session=session)._post_local_write(
                "http://127.0.0.1:23119/api/users/0/items", headers=headers
            )

        delete.assert_called_once()
        save.assert_called_once()
        self.assertEqual(headers["Zotero-API-Key"], "NEWKEY")

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

    def test_search_items_excludes_child_notes_without_titles(self):
        """Search results contain only top-level bibliographic items, not child notes."""
        session = Mock()
        items_response = Mock()
        items_response.json.return_value = [
            {"key": "PAPER", "data": {"itemType": "preprint", "title": "Paper"}},
            {
                "key": "NOTE",
                "data": {"itemType": "note", "parentItem": "PAPER"},
            },
        ]
        items_response.raise_for_status.return_value = None
        collections_response = Mock()
        collections_response.json.return_value = []
        collections_response.raise_for_status.return_value = None
        session.get.side_effect = [items_response, collections_response]

        result = ZoteroAdapter(session=session).search_items("Paper", "0", "user")

        self.assertEqual([item["item_key"] for item in result], ["PAPER"])
        self.assertEqual([item["title"] for item in result], ["Paper"])
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
