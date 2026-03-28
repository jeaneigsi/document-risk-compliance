"""Z.ai OCR client for document layout parsing."""

import base64
from pathlib import Path
from typing import List, Optional, Union
import logging

import httpx
from pydantic import ValidationError

from app.config import settings
from app.ingest.models import (
    OCRRequest,
    OCRResponse,
    PageRange,
    MAX_PAGES_PER_REQUEST,
    LayoutElement,
    BBox2D,
)

logger = logging.getLogger(__name__)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class ZaiOCRClient:
    """
    Client for Z.ai Layout Parsing API.

    Features:
    - Synchronous OCR with Markdown + structured layout output
    - Automatic PDF chunking (max 15 pages per request for safety)
    - Support for URL and base64 file input
    - Retry logic for transient failures
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.z.ai/api/paas/v4",
        timeout: float | None = None,
    ):
        """
        Initialize the Z.ai OCR client.

        Args:
            api_key: Z.ai API key (defaults to settings.OCR_API_KEY)
            base_url: API base URL
            timeout: Request timeout in seconds
        """
        raw_lower = getattr(settings, "ocr_api_key", None)
        raw_upper = getattr(settings, "OCR_API_KEY", None)
        settings_api_key = raw_lower if isinstance(raw_lower, str) else None
        if not settings_api_key:
            settings_api_key = raw_upper if isinstance(raw_upper, str) else None
        self.api_key = api_key or settings_api_key
        self.base_url = base_url
        self.timeout = float(timeout if timeout is not None else settings.ocr_api_timeout)
        self.endpoint = f"{base_url}/layout_parsing"

        if not self.api_key or self.api_key == "your_ocr_api_key_here":
            raise ValueError("OCR_API_KEY must be set in environment or passed to client")

    def _build_headers(self) -> dict[str, str]:
        """Build request headers with authentication."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_timeout(self) -> httpx.Timeout:
        """Build granular timeout configuration.

        Large PDFs are base64-encoded into JSON. Uploading that payload can hit
        the default write timeout even before OCR starts. Keep a bounded but
        much larger write/read timeout than the generic request timeout.
        """
        base = max(30.0, float(self.timeout))
        write_timeout = max(base, 180.0)
        read_timeout = max(base, 180.0)
        return httpx.Timeout(
            timeout=base,
            connect=min(30.0, base),
            write=write_timeout,
            read=read_timeout,
            pool=base,
        )

    @staticmethod
    def _encode_file_to_base64(file_path: Union[str, Path]) -> str:
        """
        Encode a file to base64 string.

        Args:
            file_path: Path to the file (PDF, JPG, PNG)

        Returns:
            Base64 encoded string
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Check file size (50MB max for PDF, 10MB for images)
        size_mb = path.stat().st_size / (1024 * 1024)
        if path.suffix.lower() == ".pdf" and size_mb > 50:
            raise ValueError(f"PDF file too large: {size_mb:.1f}MB (max 50MB)")
        elif path.suffix.lower() not in [".pdf"] and size_mb > 10:
            raise ValueError(f"Image file too large: {size_mb:.1f}MB (max 10MB)")

        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        # Add data URL prefix
        mime_type = "application/pdf" if path.suffix.lower() == ".pdf" else "image/jpeg"
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _calculate_page_ranges(total_pages: int, max_pages: int = MAX_PAGES_PER_REQUEST) -> List[PageRange]:
        """
        Split total pages into safe chunks.

        Args:
            total_pages: Total number of pages in document
            max_pages: Maximum pages per request (default: 15)

        Returns:
            List of PageRange objects
        """
        ranges: List[PageRange] = []
        start = 1

        while start <= total_pages:
            end = min(start + max_pages - 1, total_pages)
            ranges.append(PageRange(start=start, end=end))
            start = end + 1

        return ranges

    @staticmethod
    def _normalize_bbox(bbox: list[float], page_width: float | None, page_height: float | None) -> list[float]:
        """Normalize bbox to [0,1] if provider returns absolute coordinates."""
        if len(bbox) != 4:
            raise ValueError(f"BBox array must have 4 elements, got {len(bbox)}")
        x1, y1, x2, y2 = [float(v) for v in bbox]
        if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.0:
            return [_clamp01(x1), _clamp01(y1), _clamp01(x2), _clamp01(y2)]

        if page_width and page_height and page_width > 0 and page_height > 0:
            return [
                _clamp01(x1 / page_width),
                _clamp01(y1 / page_height),
                _clamp01(x2 / page_width),
                _clamp01(y2 / page_height),
            ]

        inferred_w = max(x1, x2, 1.0)
        inferred_h = max(y1, y2, 1.0)
        return [
            _clamp01(x1 / inferred_w),
            _clamp01(y1 / inferred_h),
            _clamp01(x2 / inferred_w),
            _clamp01(y2 / inferred_h),
        ]

    @classmethod
    def _parse_layout_details(cls, raw: List, page_infos: Optional[List[dict]] = None) -> List[List[LayoutElement]]:
        """
        Parse raw layout details from API response.

        Args:
            raw: Raw layout_details array from API

        Returns:
            Parsed list of pages, each containing layout elements
        """
        pages: List[List[LayoutElement]] = []

        for page_index, page_data in enumerate(raw):
            page_info = page_infos[page_index] if page_infos and page_index < len(page_infos) else {}
            page_width = page_info.get("width")
            page_height = page_info.get("height")
            elements: List[LayoutElement] = []
            for item in page_data:
                try:
                    normalized_bbox = cls._normalize_bbox(item.get("bbox_2d", []), page_width, page_height)
                    element = LayoutElement(
                        index=item.get("index"),
                        label=item.get("label"),
                        bbox_2d=BBox2D.from_array(normalized_bbox),
                        content=item.get("content", ""),
                    )
                    elements.append(element)
                except (ValidationError, ValueError) as e:
                    logger.warning(f"Failed to parse layout element: {e}")
                    continue
            pages.append(elements)

        return pages

    async def parse_document(
        self,
        file: Union[str, Path],
        is_url: bool = False,
        return_crop_images: bool = False,
        need_layout_visualization: bool = False,
        user_id: Optional[str] = None,
    ) -> OCRResponse:
        """
        Parse a document (PDF or image) with OCR.

        For PDFs with more than MAX_PAGES_PER_REQUEST pages,
        automatically splits into multiple requests and merges results.

        Args:
            file: File path or URL
            is_url: If True, file is treated as URL; otherwise as local path
            return_crop_images: Include screenshot information
            need_layout_visualization: Include detailed layout images
            user_id: End user ID for abuse monitoring

        Returns:
            OCRResponse with parsed content and layout
        """
        # Prepare file input
        if is_url:
            file_input = str(file)
        else:
            file_input = self._encode_file_to_base64(file)

        # First, try a single request to get page count
        initial_response = await self._make_request(
            OCRRequest(
                model="glm-ocr",
                file=file_input,
                return_crop_images=return_crop_images,
                need_layout_visualization=need_layout_visualization,
                user_id=user_id,
            )
        )

        # Check if we need to chunk the PDF
        total_pages = len(initial_response.layout_details)
        if total_pages <= MAX_PAGES_PER_REQUEST:
            logger.info(f"Document has {total_pages} pages, single request sufficient")
            return initial_response

        # Chunked processing for large PDFs
        logger.info(f"Document has {total_pages} pages, splitting into chunks of {MAX_PAGES_PER_REQUEST}")
        return await self._process_chunked_pdf(
            file_input=file_input,
            total_pages=total_pages,
            return_crop_images=return_crop_images,
            need_layout_visualization=need_layout_visualization,
            user_id=user_id,
        )

    async def _process_chunked_pdf(
        self,
        file_input: str,
        total_pages: int,
        return_crop_images: bool = False,
        need_layout_visualization: bool = False,
        user_id: Optional[str] = None,
    ) -> OCRResponse:
        """
        Process a large PDF in chunks and merge results.

        Args:
            file_input: Base64 encoded file or URL
            total_pages: Total number of pages
            return_crop_images: Include screenshot information
            need_layout_visualization: Include detailed layout images
            user_id: End user ID

        Returns:
            Merged OCRResponse
        """
        ranges = self._calculate_page_ranges(total_pages)
        all_md_results: List[str] = []
        all_layout_details: List[List[LayoutElement]] = []
        all_pages_info: List = []

        async with httpx.AsyncClient(timeout=self._build_timeout()) as client:
            for page_range in ranges:
                logger.info(f"Processing pages {page_range.start}-{page_range.end} ({page_range.page_count} pages)")

                response = await self._make_request(
                    OCRRequest(
                        model="glm-ocr",
                        file=file_input,
                        start_page_id=page_range.start,
                        end_page_id=page_range.end,
                        return_crop_images=return_crop_images,
                        need_layout_visualization=need_layout_visualization,
                        user_id=user_id,
                    ),
                    client=client,
                )

                all_md_results.append(response.md_results)
                all_layout_details.extend(response.layout_details)
                if response.data_info and response.data_info.pages:
                    all_pages_info.extend(response.data_info.pages)

        # Merge results
        merged_md = "\n\n".join(all_md_results)

        return OCRResponse(
            id=all_pages_info[0].get("id") if all_pages_info else "merged",
            created=all_pages_info[0].get("created") if all_pages_info else 0,
            model="glm-ocr",
            md_results=merged_md,
            layout_details=all_layout_details,
            data_info={"pages": all_pages_info} if all_pages_info else None,
            usage=None,  # Token usage not applicable for merged requests
        )

    async def _make_request(
        self,
        request: OCRRequest,
        client: Optional[httpx.AsyncClient] = None,
    ) -> OCRResponse:
        """
        Make a single OCR request to Z.ai API.

        Args:
            request: OCR request parameters
            client: Optional httpx client (for connection pooling)

        Returns:
            Parsed OCRResponse

        Raises:
            httpx.HTTPStatusError: For API errors
            ValidationError: For invalid response format
        """
        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self._build_timeout())

        try:
            logger.debug(f"Sending OCR request: {request.model_dump(exclude={'file'})}")

            response = await client.post(
                self.endpoint,
                headers=self._build_headers(),
                json=request.model_dump(exclude_none=True, by_alias=True),
            )

            response.raise_for_status()
            data = response.json()

            # Parse layout_details if present
            if "layout_details" in data and data["layout_details"]:
                pages = []
                if isinstance(data.get("data_info"), dict):
                    pages = data.get("data_info", {}).get("pages", []) or []
                data["layout_details"] = self._parse_layout_details(data["layout_details"], page_infos=pages)

            return OCRResponse(**data)

        except httpx.HTTPStatusError as e:
            logger.error(f"OCR API error: {e.response.status_code} - {e.response.text}")
            raise
        except ValidationError as e:
            logger.error(f"Failed to parse OCR response: {e}")
            raise
        finally:
            if should_close and client:
                await client.aclose()

    async def health_check(self) -> bool:
        """
        Check if the OCR API is accessible.

        Returns:
            True if API is healthy, False otherwise
        """
        try:
            # Use a minimal request with a dummy URL (will fail but checks connectivity)
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    self.base_url.replace("/layout_parsing", ""),
                    headers=self._build_headers(),
                )
                return response.status_code < 500
        except Exception as e:
            logger.warning(f"OCR health check failed: {e}")
            return False


# Singleton instance
_client: Optional[ZaiOCRClient] = None


def get_ocr_client() -> ZaiOCRClient:
    """Get or create the singleton OCR client."""
    global _client
    if _client is None:
        _client = ZaiOCRClient()
    return _client
