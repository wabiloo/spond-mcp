import os
import secrets

from dotenv import load_dotenv
import uvicorn
from mcp.server.fastmcp import FastMCP
from spond.spond import Spond
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

load_dotenv()

API_KEY = os.environ["API_KEY"]
SPOND_USERNAME = os.environ["SPOND_USERNAME"]
SPOND_PASSWORD = os.environ["SPOND_PASSWORD"]

mcp = FastMCP("Spond")


@mcp.tool()
async def list_groups() -> str:
    """List all your Spond groups with their IDs and names."""
    s = Spond(username=SPOND_USERNAME, password=SPOND_PASSWORD)
    try:
        groups = await s.get_groups()
    finally:
        await s.clientsession.close()
    if not groups:
        return "No groups found."
    return "\n".join(f"{g['id']}: {g['name']}" for g in groups)


@mcp.tool()
async def list_members(group_id: str) -> str:
    """List all members in a Spond group.

    Args:
        group_id: The group ID (from list_groups)
    """
    s = Spond(username=SPOND_USERNAME, password=SPOND_PASSWORD)
    try:
        group = await s.get_group(group_id)
    finally:
        await s.clientsession.close()
    members = group.get("members", [])
    if not members:
        return "No members found."
    lines = [
        f"{m.get('firstName', '')} {m.get('lastName', '')}: {m['id']}"
        for m in members
    ]
    return "\n".join(lines)


@mcp.tool()
async def send_group_message(group_id: str, title: str, text: str) -> str:
    """Post a message to a Spond group wall (visible to all members).

    Args:
        group_id: The group ID (from list_groups)
        title: Post title/subject (max 60 characters)
        text: The message body text
    """
    s = Spond(username=SPOND_USERNAME, password=SPOND_PASSWORD)
    try:
        await s.login()
        url = f"{s.api_url}posts/"
        data = {"groupId": group_id, "title": title[:60], "body": text, "type": "PLAIN"}
        async with s.clientsession.post(url, json=data, headers=s.auth_headers) as r:
            if r.status not in (200, 201):
                body = await r.text()
                return f"Failed ({r.status}): {body}"
    finally:
        await s.clientsession.close()
    return "Group message posted."


@mcp.tool()
async def broadcast_message(group_id: str, text: str) -> str:
    """Send a direct message to every member of a Spond group individually.

    Use this as a fallback if send_group_message fails. Sends one DM per member.

    Args:
        group_id: The group ID (from list_groups)
        text: The message text to send
    """
    s = Spond(username=SPOND_USERNAME, password=SPOND_PASSWORD)
    try:
        group = await s.get_group(group_id)
        members = group.get("members", [])
        if not members:
            return "No members found in group."
        sent, failed = 0, []
        for m in members:
            uid = m.get("id", "")
            result = await s.send_message(text=text, user=uid, group_uid=group_id)
            if result is False:
                failed.append(f"{m.get('firstName', '')} {m.get('lastName', '')}".strip())
            else:
                sent += 1
    finally:
        await s.clientsession.close()
    summary = f"Sent to {sent}/{len(members)} members."
    if failed:
        summary += f" Failed: {', '.join(failed)}."
    return summary


@mcp.tool()
async def send_message(group_id: str, user: str, text: str) -> str:
    """Send a direct message to a specific member of a Spond group.

    Args:
        group_id: The group ID (from list_groups)
        user: The member's name, email, or ID (from list_members)
        text: The message text to send
    """
    s = Spond(username=SPOND_USERNAME, password=SPOND_PASSWORD)
    try:
        result = await s.send_message(text=text, user=user, group_uid=group_id)
    finally:
        await s.clientsession.close()
    if result is False:
        return f"User '{user}' not found in the group."
    return "Message sent."


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, api_key: str) -> None:
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            token = auth.removeprefix("Bearer ").strip()
            if not token or not secrets.compare_digest(token.encode(), self.api_key.encode()):
                response = Response("Unauthorized", status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


app = BearerAuthMiddleware(mcp.streamable_http_app(), API_KEY)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
