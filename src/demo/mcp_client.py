import logging

logger = logging.getLogger(__name__)

class MCPClient:
    async def get_realtime_info(self, user_message: str) -> dict:
        logger.info("Using mock MCPClient")
        return {
            "inventory": {"status": "mocked data - MCPClient not implemented"},
            "service": {"status": "mocked data - MCPClient not implemented"},
            "offers": {"status": "mocked data - MCPClient not implemented"},
            "search": {"status": "mocked data - MCPClient not implemented"}
        }
