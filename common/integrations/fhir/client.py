"""
FHIR R4 client — works with any public FHIR server (no auth required for SMART sandbox).
Default: https://r4.smarthealthit.org
"""
import httpx
from typing import Iterator, Optional


class FHIRClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        resp = httpx.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def paginate(self, resource_type: str, params: dict = None) -> Iterator[dict]:
        """Yield every resource across all pages of a FHIR Bundle response."""
        params = dict(params or {})
        params.setdefault("_count", "100")
        url = f"{self.base_url}/{resource_type}"
        next_params: Optional[dict] = params

        while url:
            if next_params:
                resp = httpx.get(url, params=next_params, timeout=self.timeout)
            else:
                resp = httpx.get(url, timeout=self.timeout)
            resp.raise_for_status()
            bundle = resp.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource")
                if resource:
                    yield resource

            url = None
            next_params = None
            for link in bundle.get("link", []):
                if link.get("relation") == "next":
                    url = link["url"]
                    break

    def search(self, resource_type: str, params: dict) -> list[dict]:
        """Single-page search returning list of resources."""
        return list(self.paginate(resource_type, params))

    def capability(self) -> dict:
        return self.get("metadata")
