"""
models.py — Pydantic schemas for request/response
"""
from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, List


class GenerateRequest(BaseModel):
    article_url: str = Field(..., description="Public news article URL to process")
    use_gemini: Optional[bool] = Field(True, description="Whether to use Gemini for narration refinement")
    max_segments: Optional[int] = Field(8, ge=2, le=20, description="Max number of video segments")


class Segment(BaseModel):
    index: int
    start_time: float          # seconds
    end_time: float
    headline: str
    narration: str
    image_url: Optional[str] = None
    image_path: Optional[str] = None
    visual_prompt: str


class ArticleData(BaseModel):
    title: str
    text: str
    url: str
    top_image: Optional[str] = None
    images: List[str] = []
    authors: List[str] = []
    published_date: Optional[str] = None
    source_domain: str
    word_count: int
    extraction_method: str  # newspaper3k | readability | beautifulsoup


class Script(BaseModel):
    article: ArticleData
    segments: List[Segment]
    total_duration: float
    overall_headline: str
    qa_score: float


class GenerateResponse(BaseModel):
    success: bool
    job_id: str
    script: Optional[Script] = None
    video_path: Optional[str] = None
    video_url: Optional[str] = None
    error: Optional[str] = None
    processing_time: float


class JobStatusResponse(BaseModel):
    job_id: str
    status: str   # pending | processing | done | failed
    progress: int  # 0-100
    message: str
    result: Optional[GenerateResponse] = None
