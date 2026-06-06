"""ArrClient — shared API surface for Sonarr, Radarr, Lidarr, Prowlarr, Readarr."""

from __future__ import annotations

from dataclasses import dataclass, field

from arr_mcp.services.base import ApiResult, BaseServiceClient


@dataclass
class SystemStatus:
    """Parsed response from /api/v3/system/status."""

    app_name: str
    version: str
    raw: dict  # type: ignore[type-arg]


@dataclass
class QueueItem:
    """One item from /api/v3/queue."""

    id: int
    title: str
    status: str
    tracked_download_state: str
    size_left_bytes: int
    raw: dict  # type: ignore[type-arg]


@dataclass
class HealthItem:
    """One item from /api/v3/health."""

    source: str
    type: str  # "ok" | "notice" | "warning" | "error"
    message: str
    wiki_url: str


@dataclass
class WantedMissing:
    """Aggregated result from /api/v3/wanted/missing."""

    total_records: int
    records: list[dict] = field(default_factory=list)  # type: ignore[type-arg]


class ArrClient(BaseServiceClient):
    """HTTP client for the shared /api/v3 surface of all *arr apps."""

    def _health_path(self) -> str:
        return "/api/v3/system/status"

    async def system_status(self) -> ApiResult:
        """Fetch application version and status."""
        result = await self.get("/api/v3/system/status")
        if result.ok and isinstance(result.data, dict):
            data = result.data
            result.data = SystemStatus(  # type: ignore[assignment]
                app_name=data.get("appName", ""),
                version=data.get("version", ""),
                raw=data,
            )
        return result

    async def get_queue(self) -> ApiResult:
        """Fetch the current download queue."""
        result = await self.get("/api/v3/queue")
        if result.ok and isinstance(result.data, dict):
            records = result.data.get("records", [])
            result.data = [  # type: ignore[assignment]
                QueueItem(
                    id=r.get("id", 0),
                    title=r.get("title", ""),
                    status=r.get("status", ""),
                    tracked_download_state=r.get("trackedDownloadState", ""),
                    size_left_bytes=r.get("sizeLeft", 0),
                    raw=r,
                )
                for r in records
            ]
        return result

    async def get_health(self) -> ApiResult:
        """Fetch the app's internal health checks."""
        result = await self.get("/api/v3/health")
        if result.ok and isinstance(result.data, list):
            result.data = [  # type: ignore[assignment]
                HealthItem(
                    source=r.get("source", ""),
                    type=r.get("type", ""),
                    message=r.get("message", ""),
                    wiki_url=r.get("wikiUrl", ""),
                )
                for r in result.data
            ]
        return result

    async def get_wanted_missing(self, page_size: int = 10) -> ApiResult:
        """Fetch wanted/missing items (first page)."""
        result = await self.get(
            "/api/v3/wanted/missing",
            pageSize=str(page_size),
            sortKey="airDateUtc",
        )
        if result.ok and isinstance(result.data, dict):
            result.data = WantedMissing(  # type: ignore[assignment]
                total_records=result.data.get("totalRecords", 0),
                records=result.data.get("records", []),
            )
        return result
