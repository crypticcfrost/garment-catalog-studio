import json
import time
import asyncio
from typing import Dict, List
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        if session_id not in self.connections:
            self.connections[session_id] = []
        self.connections[session_id].append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.connections:
            try:
                self.connections[session_id].remove(websocket)
            except ValueError:
                pass

    async def send_event(
        self,
        session_id: str,
        event_type: str,
        data: dict,
        specific_ws: WebSocket = None,
    ):
        message = json.dumps(
            {
                "type": event_type,
                "session_id": session_id,
                "data": data,
                "ts": time.time(),
            }
        )

        if specific_ws:
            try:
                await specific_ws.send_text(message)
            except Exception:
                pass
            return

        if session_id not in self.connections:
            return

        dead = []
        for ws in self.connections[session_id]:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.connections[session_id].remove(ws)

    def has_connections(self, session_id: str) -> bool:
        return bool(self.connections.get(session_id))
