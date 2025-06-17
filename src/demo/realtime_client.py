import logging

logger = logging.getLogger(__name__)

class RealtimeClient:
    async def get_realtime_info(self, message: str) -> dict:
        logger.info("Using mock RealtimeClient")
        return {
            "current_time": "mocked time - RealtimeClient not implemented",
            "response": "mocked response - RealtimeClient not implemented"
        }
