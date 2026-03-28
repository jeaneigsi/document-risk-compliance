"""OCR data models for Z.ai Layout Parsing API."""

from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class LayoutLabel(str, Enum):
    """Layout element types from Z.ai API."""
    TEXT = "text"
    IMAGE = "image"
    FORMULA = "formula"
    TABLE = "table"


class BBox2D(BaseModel):
    """Normalized 2D bounding box [x1, y1, x2, y2] where 0 <= x,y <= 1."""
    x1: float = Field(..., ge=0.0, le=1.0)
    y1: float = Field(..., ge=0.0, le=1.0)
    x2: float = Field(..., ge=0.0, le=1.0)
    y2: float = Field(..., ge=0.0, le=1.0)

    @classmethod
    def from_array(cls, arr: List[float]) -> "BBox2D":
        """Create BBox2D from [x1, y1, x2, y2] array."""
        if len(arr) != 4:
            raise ValueError(f"BBox array must have 4 elements, got {len(arr)}")
        return cls(x1=arr[0], y1=arr[1], x2=arr[2], y2=arr[3])

    def to_array(self) -> List[float]:
        """Convert to [x1, y1, x2, y2] array."""
        return [self.x1, self.y1, self.x2, self.y2]


class LayoutElement(BaseModel):
    """A single layout element (text, image, formula, or table)."""
    index: int = Field(..., description="Element index")
    label: LayoutLabel = Field(..., description="Element type")
    bbox_2d: BBox2D = Field(..., description="Normalized coordinates")
    content: str = Field(..., description="Element content (text/image URL/table HTML)")


class PageInfo(BaseModel):
    """Information about a parsed page."""
    width: int = Field(..., description="Page width in pixels")
    height: int = Field(..., description="Page height in pixels")


class TokenUsage(BaseModel):
    """Token usage statistics."""
    prompt_tokens: int = Field(0, description="Input tokens")
    completion_tokens: int = Field(0, description="Output tokens")
    total_tokens: int = Field(0, description="Total tokens")


class OCRPageResult(BaseModel):
    """OCR results for a single page."""
    layout_details: List[LayoutElement] = Field(default_factory=list)
    page_info: Optional[PageInfo] = None


class OCRResponse(BaseModel):
    """Complete OCR response from Z.ai Layout Parsing API."""
    id: str = Field(..., description="Task ID")
    created: int = Field(..., description="Unix timestamp")
    model: str = Field(..., description="Model name (e.g., GLM-OCR)")
    md_results: str = Field(..., description="Recognition result in Markdown format")
    layout_details: List[List[LayoutElement]] = Field(
        default_factory=list,
        description="Detailed layout information per page"
    )
    data_info: Optional["DataInfo"] = None
    usage: Optional[TokenUsage] = None
    request_id: Optional[str] = None


class DataInfo(BaseModel):
    """Document metadata."""
    pages: List[PageInfo] = Field(default_factory=list)


# Update forward references
OCRResponse.model_rebuild()


class OCRRequest(BaseModel):
    """Request parameters for Z.ai OCR API."""
    model: str = Field(default="glm-ocr", description="Model code")
    file: str = Field(..., description="Image or PDF document (URL or base64)")
    return_crop_images: bool = Field(default=False, description="Return screenshot info")
    need_layout_visualization: bool = Field(default=False, description="Return detailed layout")
    start_page_id: Optional[int] = Field(None, ge=1, description="Start page for PDF")
    end_page_id: Optional[int] = Field(None, ge=1, description="End page for PDF")
    user_id: Optional[str] = Field(None, min_length=6, max_length=128, description="End user ID")


class PageRange(BaseModel):
    """A range of pages to process together."""
    start: int = Field(..., ge=1, description="Start page (1-indexed)")
    end: int = Field(..., ge=1, description="End page (inclusive)")

    @property
    def page_count(self) -> int:
        """Number of pages in this range."""
        return self.end - self.start + 1


MAX_PAGES_PER_REQUEST = 15
"""Maximum pages per OCR request for safety and reliability."""
