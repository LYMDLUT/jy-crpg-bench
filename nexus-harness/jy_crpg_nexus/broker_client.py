"""A small client for the broker, used by the task on the Host.

Three calls: open a session, close it with a reason, and file the token meter.
The broker's own contract is in bench/broker.py; this only speaks it.
"""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class Session:
    id: str
    agent: str
    base_url: str          # carries the play token in its path
    help_url: str
    seconds: int
    actions_budget: int | None
    ends_at: float
    raw: dict[str, Any]

    @property
    def api_url(self) -> str:
        return self.base_url.rstrip("/") + "/api"


class BrokerError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"broker answered {status}: {body}")
        self.status = status
        self.body = body


def _request(method: str, url: str, payload: dict | None = None,
             headers: dict | None = None, timeout: float = 180) -> tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        body = raw
    return status, body


class BrokerClient:
    def __init__(self, broker_url: str, operator_token: str | None = None):
        self.broker_url = broker_url.rstrip("/")
        self.operator_token = operator_token

    async def _call(self, *args, **kwargs) -> tuple[int, Any]:
        return await asyncio.to_thread(_request, *args, **kwargs)

    async def new_session(self, agent: str, *, minutes: int, actions: int = 0,
                          publish: bool = False) -> Session:
        """POST /session. ``actions`` > 0 asks for a decision budget; the
        minutes are then the ceiling on how long the machine is held."""
        payload: dict[str, Any] = {"agent": agent, "minutes": minutes,
                                   "publish": publish}
        if actions > 0:
            payload["actions"] = actions
        status, body = await self._call("POST", f"{self.broker_url}/session", payload)
        if status != 200 or not isinstance(body, dict) or not body.get("ok"):
            raise BrokerError(status, body)
        if actions > 0 and body.get("actions_budget") != actions:
            # An older broker ignores the field and hands out a clock run. That
            # is a different experiment; refuse rather than record it as this one.
            raise BrokerError(status, {"error": "broker did not honour the decision budget",
                                       "asked": actions, "got": body.get("actions_budget")})
        return Session(id=body["session"], agent=body["agent"],
                       base_url=body["base_url"], help_url=body["help_url"],
                       seconds=int(body["seconds"]),
                       actions_budget=body.get("actions_budget"),
                       ends_at=float(body["ends_at"]), raw=body)

    async def end_session(self, session: Session, reason: str, detail: str = "") -> dict:
        """POST /api/end through the session's play address with the operator
        token. Without the token the broker's session server answers 404, which
        is reported, not raised: closing the run is a courtesy to the record,
        and the run still ends at its clock."""
        if not self.operator_token:
            return {"ok": False, "skipped": "no operator token"}
        status, body = await self._call(
            "POST", f"{session.api_url}/end",
            {"reason": reason, "detail": detail},
            headers={"X-Reset-Token": self.operator_token}, timeout=30)
        return {"status": status, "body": body}

    async def report_usage(self, session: Session, usage: dict[str, int]) -> dict:
        """POST usage through the play address. The broker wants the harness's
        meter: input, output, cacheRead, cacheWrite, totalTokens."""
        status, body = await self._call(
            "POST", f"{session.base_url.rstrip('/')}/usage", usage,
            headers={"X-Agent": session.agent}, timeout=30)
        return {"status": status, "body": body}

    async def state(self, session: Session) -> tuple[int, Any]:
        """GET the session's /status as the operator: (http status, body).
        200 while the run plays; 410 with the run's own summary once it is
        over and the session process has gone."""
        headers = {"X-Reset-Token": self.operator_token} if self.operator_token else {}
        return await self._call("GET", f"{session.base_url.rstrip('/')}/status",
                                headers=headers, timeout=15)

    async def status(self, session: Session) -> dict | None:
        """The live /status body, or None once the run is over (or on error)."""
        status, body = await self.state(session)
        return body if status == 200 and isinstance(body, dict) else None

    async def ended_payload(self, session: Session) -> dict | None:
        """The broker's 410 body: the run's summary once it has ended."""
        status, body = await self.state(session)
        if status == 410 and isinstance(body, dict):
            return dict(body, ended=True)
        return None
