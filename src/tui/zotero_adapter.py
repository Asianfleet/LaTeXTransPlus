"""Zotero integration adapter for the Textual UI."""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from pathlib import Path
from typing import Any

import requests


class ZoteroAdapter:
    """Adapter for Zotero library search and PDF child attachment upload."""

    def __init__(
        self,
        python_cmd: list[str] | None = None,
        script_path: str = "",
        api_key: str = "",
        session: requests.Session | None = None,
        api_base_url: str = "https://api.zotero.org",
        local_api_base: str = "http://127.0.0.1:23119/api",
    ) -> None:
        """Initialize the adapter with CLI and Web API settings."""
        self.python_cmd = list(python_cmd or [])
        self.script_path = script_path
        self.api_key = api_key
        self.session = session if session is not None else requests.Session()
        self.api_base_url = api_base_url.rstrip("/")
        self.local_api_base = local_api_base.rstrip("/")

    def list_libraries(self) -> list[dict[str, Any]]:
        """List Zotero libraries through the local Zotero API."""
        libraries = [
            {
                "library_id": "0",
                "library_type": "user",
                "name": "用户库",
            }
        ]

        groups_response = self.session.get(f"{self.local_api_base}/users/0/groups")
        groups_response.raise_for_status()
        for group in groups_response.json() or []:
            data = group.get("data", {}) if isinstance(group, dict) else {}
            library_id = group.get("id") if isinstance(group, dict) else None
            if library_id is None:
                library_id = data.get("id")
            libraries.append(
                {
                    "library_id": str(library_id),
                    "library_type": "group",
                    "name": str(data.get("name") or group.get("name") or library_id),
                }
            )
        return libraries

    def search_items(self, query: str, library_id: str, library_type: str) -> list[dict[str, Any]]:
        """Search existing Zotero items in a selected library through the local API."""
        items = self._get_local_items(library_id, library_type, {"q": query, "itemType": "-attachment"})
        collection_names = self._get_collection_names(library_id, library_type)
        return [self._normalize_local_item(item, library_id, library_type, collection_names) for item in items]

    def match_items_by_archive_id(self, arxiv_id: str, library_id: str, library_type: str) -> list[dict[str, Any]]:
        """Return local Zotero items whose archive ID field contains the arXiv ID."""
        items = self._get_local_items(library_id, library_type, {"itemType": "-attachment"})
        collection_names = self._get_collection_names(library_id, library_type)
        normalized = [self._normalize_local_item(item, library_id, library_type, collection_names) for item in items]
        return [
            item
            for item in normalized
            if arxiv_id and arxiv_id in str(item.get("archive_id") or "")
        ]

    def attach_pdf(self, item_key: str, pdf_path: str, library_id: str, library_type: str) -> dict[str, Any]:
        """Attach a translated PDF file to an existing Zotero item."""
        path = Path(pdf_path)
        if not path.is_absolute():
            path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(str(path))

        attachment_key = self._create_child_attachment(item_key, path, library_id, library_type)
        auth_payload = self._authorize_upload(attachment_key, path, library_id, library_type)
        if auth_payload.get("exists") == 1:
            return {"attachment_key": attachment_key, "status": "exists"}

        upload_body = (
            str(auth_payload["prefix"]).encode("utf-8")
            + path.read_bytes()
            + str(auth_payload["suffix"]).encode("utf-8")
        )
        upload_response = self.session.post(
            auth_payload["url"],
            data=upload_body,
            headers={"Content-Type": auth_payload["contentType"]},
        )
        upload_response.raise_for_status()
        self._register_upload(attachment_key, auth_payload["uploadKey"], library_id, library_type)
        return {"attachment_key": attachment_key, "status": "uploaded"}

    def check_local_write_support(self) -> str:
        """检查本地服务是否提供带实例标识的可写 API。"""
        response = self.session.get(f"{self.local_api_base}/", timeout=5)
        response.raise_for_status()
        server_id = response.headers.get("Zotero-Server-ID", "")
        if not server_id:
            raise RuntimeError("当前 Zotero 版本不支持本地写入，或本地 API 未启用。")
        return server_id

    def attach_pdf_local(self, item_key: str, pdf_path: str, library_id: str, library_type: str) -> dict[str, Any]:
        """经 Zotero 本地可写 API 创建子附件并上传 PDF。"""
        path = Path(pdf_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(str(path))
        server_id = self.check_local_write_support()
        headers = {
            "Zotero-API-Key": self._authorize_local_write(server_id),
            "Zotero-API-Version": "3",
            "Zotero-Server-ID": server_id,
        }
        attachment_key = self._create_child_attachment(
            item_key, path, library_id, library_type,
            api_base=self.local_api_base, headers=headers,
        )
        auth_payload = self._authorize_upload(
            attachment_key, path, library_id, library_type,
            api_base=self.local_api_base, headers=headers,
        )
        if auth_payload.get("exists") == 1:
            return {"attachment_key": attachment_key, "status": "exists"}
        upload_body = (
            str(auth_payload["prefix"]).encode("utf-8")
            + path.read_bytes()
            + str(auth_payload["suffix"]).encode("utf-8")
        )
        upload_response = self.session.post(
            auth_payload["url"], data=upload_body,
            headers={"Content-Type": auth_payload["contentType"]},
        )
        upload_response.raise_for_status()
        self._register_upload(
            attachment_key, auth_payload["uploadKey"], library_id, library_type,
            api_base=self.local_api_base, headers=headers,
        )
        return {"attachment_key": attachment_key, "status": "uploaded"}

    def _authorize_local_write(self, server_id: str) -> str:
        """向 Zotero 请求仅用于当前导入操作的本地写入 key。"""
        authorization = self.session.post(
            f"{self.local_api_base}/local/authorize",
            json={"appName": "LaTeXTransPlus"},
            headers={"Zotero-Server-ID": server_id},
            timeout=60,
        )
        authorization.raise_for_status()
        local_key = authorization.json().get("key", "")
        if not local_key:
            raise RuntimeError("Zotero 未授予本地 API 写入权限。")
        return local_key

    def _post_local_write(self, url: str, **kwargs: Any) -> requests.Response:
        """一次授权过期时重新授权并重试当前本地写请求。"""
        response = self.session.post(url, **kwargs)
        if response.status_code == 401:
            kwargs["headers"]["Zotero-API-Key"] = self._authorize_local_write(
                kwargs["headers"]["Zotero-Server-ID"]
            )
            response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return response

    def create_note(
        self,
        item_key: str,
        title: str,
        note: str,
        library_id: str,
        library_type: str,
    ) -> dict[str, Any]:
        """Create a Zotero child note containing the supplied Markdown text."""
        prefix = self._library_prefix(library_id, library_type)
        payload = [
            {
                "itemType": "note",
                "parentItem": item_key,
                "title": title,
                "note": note,
                "tags": [],
                "relations": {},
            }
        ]
        response = self.session.post(
            f"{self.api_base_url}/{prefix}/items",
            json=payload,
            headers={
                **self._api_headers(),
                "Content-Type": "application/json",
                "Zotero-Write-Token": uuid.uuid4().hex,
            },
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"Zotero did not return a note key: {body}")
        successful = body.get("successful") or body.get("success") or {}
        if not isinstance(successful, dict):
            raise RuntimeError(f"Zotero did not return a note key: {body}")
        first_result = successful.get("0")
        if isinstance(first_result, dict) and first_result.get("key"):
            return {"item_key": str(first_result["key"])}
        if isinstance(first_result, str):
            return {"item_key": first_result}
        raise RuntimeError(f"Zotero did not return a note key: {body}")

    def _get_local_items(
        self,
        library_id: str,
        library_type: str,
        params: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Fetch top-level item rows from the local Zotero API."""
        response = self.session.get(
            f"{self.local_api_base}/{self._library_prefix(library_id, library_type)}/items",
            params=params,
        )
        response.raise_for_status()
        body = response.json() or []
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected Zotero local API response: {body}")
        return body

    def _normalize_local_item(
        self,
        item: dict[str, Any],
        library_id: str,
        library_type: str,
        collection_names: dict[str, str],
    ) -> dict[str, Any]:
        """Convert a local API item into the row data used by the TUI."""
        data = item.get("data", {}) if isinstance(item, dict) else {}
        library = item.get("library", {}) if isinstance(item, dict) else {}
        collections = data.get("collections") or item.get("collections") or []
        return {
            "item_key": str(item.get("key") or data.get("key") or ""),
            "title": str(data.get("title") or item.get("title") or ""),
            "library_id": str(library.get("id") or library_id),
            "library_type": str(library.get("type") or library_type),
            "library_name": str(library.get("name") or library.get("libraryName") or library_id),
            "collection_names": [collection_names.get(str(collection), str(collection)) for collection in collections],
            "archive_id": str(data.get("archiveLocation") or data.get("archiveID") or data.get("archiveId") or ""),
        }

    def _get_collection_names(self, library_id: str, library_type: str) -> dict[str, str]:
        """Return a mapping from Zotero collection keys to display names."""
        response = self.session.get(f"{self.local_api_base}/{self._library_prefix(library_id, library_type)}/collections")
        response.raise_for_status()
        body = response.json() or []
        if not isinstance(body, list):
            raise RuntimeError(f"Unexpected Zotero collection response: {body}")
        names: dict[str, str] = {}
        for collection in body:
            if not isinstance(collection, dict):
                continue
            data = collection.get("data", {})
            key = str(collection.get("key") or data.get("key") or "")
            name = str(data.get("name") or collection.get("name") or key)
            if key:
                names[key] = name
        return names

    def _library_prefix(self, library_id: str, library_type: str) -> str:
        """Return the Zotero Web API library prefix."""
        if library_type == "user":
            return f"users/{library_id}"
        if library_type == "group":
            return f"groups/{library_id}"
        raise ValueError(f"Unsupported Zotero library type for file upload: {library_type}")

    def _api_headers(self) -> dict[str, str]:
        """Return common Zotero Web API headers."""
        return {
            "Zotero-API-Key": self.api_key,
            "Zotero-API-Version": "3",
        }

    def _create_child_attachment(self, item_key: str, pdf_path: Path, library_id: str, library_type: str, *, api_base: str | None = None, headers: dict[str, str] | None = None) -> str:
        """Create a child attachment item and return its item key."""
        prefix = self._library_prefix(library_id, library_type)
        payload = [
            {
                "itemType": "attachment",
                "parentItem": item_key,
                "linkMode": "imported_file",
                "title": pdf_path.stem,
                "note": "",
                "tags": [],
                "relations": {},
                "contentType": mimetypes.guess_type(pdf_path.name)[0] or "application/pdf",
                "charset": "",
                "filename": pdf_path.name,
                "md5": None,
                "mtime": None,
            }
        ]
        post = self._post_local_write if api_base == self.local_api_base else self.session.post
        response = post(
            f"{api_base or self.api_base_url}/{prefix}/items",
            json=payload,
            headers={
                **(headers if headers is not None else self._api_headers()),
                "Content-Type": "application/json",
                "Zotero-Write-Token": uuid.uuid4().hex,
            },
        )
        response.raise_for_status()
        body = response.json()
        successful = body.get("successful") or body.get("success") or {}
        first_result = successful.get("0")
        if isinstance(first_result, dict) and first_result.get("key"):
            return first_result["key"]
        if isinstance(first_result, str):
            return first_result
        raise RuntimeError(f"Zotero did not return an attachment key: {body}")

    def _authorize_upload(
        self,
        attachment_key: str,
        pdf_path: Path,
        library_id: str,
        library_type: str,
        *,
        api_base: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Request Zotero upload authorization for the attachment file."""
        prefix = self._library_prefix(library_id, library_type)
        file_bytes = pdf_path.read_bytes()
        data = {
            "md5": hashlib.md5(file_bytes).hexdigest(),
            "filename": pdf_path.name,
            "filesize": str(len(file_bytes)),
            "mtime": str(int(pdf_path.stat().st_mtime * 1000)),
            "contentType": mimetypes.guess_type(pdf_path.name)[0] or "application/pdf",
        }
        post = self._post_local_write if api_base == self.local_api_base else self.session.post
        response = post(
            f"{api_base or self.api_base_url}/{prefix}/items/{attachment_key}/file",
            data=data,
            headers={**(headers if headers is not None else self._api_headers()), "If-None-Match": "*"},
        )
        response.raise_for_status()
        return response.json()

    def _register_upload(self, attachment_key: str, upload_key: str, library_id: str, library_type: str, *, api_base: str | None = None, headers: dict[str, str] | None = None) -> None:
        """Register a completed Zotero file upload."""
        prefix = self._library_prefix(library_id, library_type)
        post = self._post_local_write if api_base == self.local_api_base else self.session.post
        response = post(
            f"{api_base or self.api_base_url}/{prefix}/items/{attachment_key}/file",
            data={"upload": upload_key},
            headers={**(headers if headers is not None else self._api_headers()), "If-None-Match": "*"},
        )
        response.raise_for_status()
