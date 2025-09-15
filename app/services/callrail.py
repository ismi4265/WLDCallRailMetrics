# app/services/callrail.py
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)


class CallRailClient:
    def __init__(self, api_key: str, account_id: str, base_url: str = "https://api.callrail.com/v3"):
        self.api_key = api_key
        self.account_id = account_id
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f'Token token="{self.api_key}"',
        })

    def _list_url(self) -> str:
        return f"{self.base_url}/a/{self.account_id}/calls.json"

    def list_calls(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        date_range: Optional[str] = None,
        per_page: int = 250,
        relative: bool = True,
        fields: Optional[Iterable[str]] = None,
        tags_filter: Optional[Iterable[str]] = None,
        company_id: Optional[str] = None,
        sort: str = "start_time",
        order: str = "desc",
        timezone: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "per_page": per_page,
            "order": order,
            "sort": sort,
        }
        if relative:
            params["relative_pagination"] = "true"
        if date_range:
            params["date_range"] = date_range
        else:
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date
        if timezone:
            params["time_zone"] = timezone

        base_fields = set(fields or [])
        base_fields.update({
            "tags",
            "agent_email",
            "company_id",
            "company_name",
            "source_name",
            "business_phone_number",
            "customer_phone_number",
        })
        params["fields"] = ",".join(sorted(base_fields))

        url = self._list_url()

        def first_url() -> str:
            if tags_filter:
                qs_items: List[Tuple[str, str]] = [(k, str(v)) for k, v in params.items() if k != "fields"]
                qs_items.append(("fields", params["fields"]))
                for t in tags_filter:
                    qs_items.append(("tags", t))
                return f"{url}?{urlencode(qs_items)}"
            return f"{url}?{urlencode(params)}"

        next_url: Optional[str] = first_url()
        calls: List[Dict[str, Any]] = []

        while next_url:
            resp = self.session.get(next_url, timeout=30)
            if resp.status_code != 200:
                log.error("CallRail list_calls error %s: %s", resp.status_code, resp.text)
                resp.raise_for_status()
            payload = resp.json()
            page_calls = payload.get("calls", []) or []
            calls.extend(page_calls)

            if payload.get("has_next_page") and payload.get("next_page"):
                next_url = payload["next_page"]
            else:
                next_url = None

        return calls
