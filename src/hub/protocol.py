"""Wire protocol version enforcement.

The Hub owns the API contract. Spoke clients send an
``X-Protocol-Version`` header on every request. This middleware
rejects requests whose version is not in the SUPPORTED_VERSIONS set.

Requests without the header are allowed through (browser, curl,
frontend) so the middleware only gates Spoke-to-Hub traffic.
"""

import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

# Versions the Hub currently accepts. Add new entries here when the
# wire schema evolves (e.g. {"v1", "v2"}).
SUPPORTED_VERSIONS = frozenset({"v1"})

# Header name sent by Spoke clients.
PROTOCOL_VERSION_HEADER = "X-Protocol-Version"


class ProtocolVersionMiddleware(BaseHTTPMiddleware):
    """Reject Spoke requests that declare an unsupported protocol version.

    If the header is absent the request is passed through unchanged —
    this keeps the frontend, OpenAPI docs, and health checks working
    without modification.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        version = request.headers.get(PROTOCOL_VERSION_HEADER)

        if version is not None and version not in SUPPORTED_VERSIONS:
            logger.warning(
                "Rejected request with unsupported protocol version %r "
                "from %s %s",
                version,
                request.method,
                request.url.path,
            )
            return Response(
                content=f"Unsupported protocol version: {version}. "
                f"Supported: {', '.join(sorted(SUPPORTED_VERSIONS))}",
                status_code=400,
                media_type="text/plain",
            )

        return await call_next(request)
