"""A local clock; network integrations must never masquerade as current facts."""

from datetime import datetime
from zoneinfo import ZoneInfo


class RealtimeClient:
    def get_realtime_info(self):
        return {"current_time": datetime.now(ZoneInfo("America/Chicago")).isoformat()}
