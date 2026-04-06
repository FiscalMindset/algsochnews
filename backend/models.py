"""
models.py — Pydantic schemas for request/response and broadcast workflow data.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    article_url: str = Field(..., description="Public news article URL to process")
    use_gemini: Optional[bool] = Field(
        True,
        description="Whether to use Gemini for editorial refinement",
    )
    max_segments: Optional[int] = Field(
        6,
        ge=4,
        le=12,
        description="Max number of screenplay/video segments including intro and close",
    )
    transition_intensity: Optional[Literal["subtle", "standard", "dramatic"]] = Field(
        "standard",
        description="Transition intensity profile for edit pacing and visual energy.",
    )
    transition_profile: Optional[Literal["auto", "general", "crisis", "sports", "politics"]] = Field(
        "auto",
        description="Story transition grammar profile. auto infers from article content.",
    )
    delivery_mode: Optional[Literal["full_video", "editorial_only"]] = Field(
        "full_video",
        description="Output mode: full_video renders MP4, editorial_only skips TTS/render and returns editorial artifacts only.",
    )


class ExtractionCandidate(BaseModel):
    method: str
    score: float
    title: str = ""
    word_count: int = 0
    image_count: int = 0
    selected: bool = False
    preview_excerpt: str = ""
    kept_ratio: float = 1.0
    dropped_samples: List[str] = Field(default_factory=list)
    image_preview: List[str] = Field(default_factory=list)
    status: str = "accepted"
    reason: str = ""
    selector_used: str = ""
    dom_tags: List[str] = Field(default_factory=list)
    extraction_signals: List[str] = Field(default_factory=list)
    method_details: Dict[str, Any] = Field(default_factory=dict)


class AgentArtifact(BaseModel):
    label: str
    value: Any
    kind: str = "text"
    artifact_type: str = "output"
    timestamp: Optional[float] = None


class TraceEvent(BaseModel):
    ts: float
    agent_key: str
    agent_name: str
    event_type: str
    message: str
    input_payload: Any = None
    tools: List[str] = Field(default_factory=list)
    output_payload: Any = None
    decision: Optional[str] = None
    route_to: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


class ModelVerification(BaseModel):
    configured_model: str
    selected_model: str
    available_models: List[str] = Field(default_factory=list)
    upgraded: bool = False
    verification_ok: bool = False
    note: str = ""


class AgentTrace(BaseModel):
    key: str
    name: str
    role: str
    status: str
    progress: int = 0
    summary: str = ""
    retry_count: int = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    branch: Optional[str] = None
    outputs: List[AgentArtifact] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    current_input: Any = None
    tools_used: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    event_count: int = 0
    node_visits: int = 0
    llm_model: Optional[str] = None
    updated_at: Optional[float] = None


class ReviewCriterion(BaseModel):
    key: str
    label: str
    score: int
    max_score: int = 5
    reason: str
    evidence: List[str] = Field(default_factory=list)
    recommendation: str = ""


class SegmentQADiagnostic(BaseModel):
    segment_id: int
    headline: str = ""
    score: int = 0
    status: str = ""
    strengths: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    recommendation: str = ""


class QAReview(BaseModel):
    passed: bool
    overall_average: float
    retry_rounds: int = 0
    retry_decision: str = "finalize"
    weak_segments: List[int] = Field(default_factory=list)
    hard_failures: List[str] = Field(default_factory=list)
    gating: Dict[str, Any] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)
    criteria: List[ReviewCriterion] = Field(default_factory=list)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    score_explanation: str = ""
    segment_diagnostics: List[SegmentQADiagnostic] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)


class RenderQualityReview(BaseModel):
    passed: bool
    overall_score: float
    summary: str = ""
    verdict: str = "review"
    strengths: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    telemetry: Dict[str, Any] = Field(default_factory=dict)


class TranscriptCue(BaseModel):
    id: str
    segment_id: int
    start_time: float
    end_time: float
    start_timecode: str
    end_timecode: str
    text: str
    speaker: str = "anchor"
    emphasis: str = ""
    lane: str = "program"


class RundownCue(BaseModel):
    segment_id: int
    slug: str
    start_timecode: str
    end_timecode: str
    editorial_focus: str
    lower_third: str
    ticker_text: str
    camera_motion: str
    visual_source_kind: str
    control_room_cue: str
    director_note: str


class Segment(BaseModel):
    segment_id: int
    index: int
    segment_type: str
    start_time: float
    end_time: float
    start_timecode: str
    end_timecode: str
    duration: float
    layout: str
    anchor_narration: str
    main_headline: str
    subheadline: str
    top_tag: str
    left_panel: str
    right_panel: str
    source_text: str
    source_excerpt: str
    source_image_url: Optional[str] = None
    ai_support_visual_prompt: Optional[str] = None
    transition: str
    transition_profile: str = "general"
    transition_intensity: str = "standard"
    story_beat: str = ""
    editorial_focus: str = ""
    lower_third: str = ""
    ticker_text: str = ""
    camera_motion: str = ""
    visual_source_kind: str = ""
    visual_confidence: float = 0.0
    control_room_cue: str = ""
    director_note: str = ""
    source_visual_used: bool = False
    scene_image_url: Optional[str] = None
    scene_image_path: Optional[str] = None
    html_frame_url: Optional[str] = None
    html_frame_path: Optional[str] = None
    support_image_path: Optional[str] = None
    image_url: Optional[str] = None
    image_path: Optional[str] = None
    visual_prompt: str = ""
    headline_reason: str = ""
    visual_rationale: str = ""
    factual_points: List[str] = Field(default_factory=list)
    headline: str = ""
    narration: str = ""
    transcript_cues: List[TranscriptCue] = Field(default_factory=list)


class ArticleData(BaseModel):
    title: str
    text: str
    url: str
    top_image: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    authors: List[str] = Field(default_factory=list)
    published_date: Optional[str] = None
    source_domain: str
    word_count: int
    extraction_method: str
    extraction_score: float = 0.0
    extraction_candidates: List[ExtractionCandidate] = Field(default_factory=list)
    extraction_attempts: List[Dict[str, Any]] = Field(default_factory=list)


class Script(BaseModel):
    article_url: str
    source_title: str
    article: ArticleData
    segments: List[Segment]
    live_transcript: List[TranscriptCue] = Field(default_factory=list)
    rundown: List[RundownCue] = Field(default_factory=list)
    total_duration: float
    video_duration_sec: int
    overall_headline: str
    screenplay_text: str
    qa_score: float
    review: Optional[QAReview] = None
    render_review: Optional[RenderQualityReview] = None
    workflow_overview: Dict[str, Any] = Field(default_factory=dict)
    model_verification: Optional[ModelVerification] = None
    route_history: List[str] = Field(default_factory=list)
    llm_enhanced: bool = False
    delivery_mode: Literal["full_video", "editorial_only"] = "full_video"


class GenerateResponse(BaseModel):
    success: bool
    job_id: str
    script: Optional[Script] = None
    agents: List[AgentTrace] = Field(default_factory=list)
    activity_log: List[str] = Field(default_factory=list)
    trace_events: List[TraceEvent] = Field(default_factory=list)
    runtime_logs: List[str] = Field(default_factory=list)
    model_verification: Optional[ModelVerification] = None
    video_path: Optional[str] = None
    video_url: Optional[str] = None
    error: Optional[str] = None
    processing_time: float


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: int
    message: str
    preview_video_url: Optional[str] = None
    agents: List[AgentTrace] = Field(default_factory=list)
    activity_log: List[str] = Field(default_factory=list)
    trace_events: List[TraceEvent] = Field(default_factory=list)
    runtime_logs: List[str] = Field(default_factory=list)
    workflow_overview: Dict[str, Any] = Field(default_factory=dict)
    review: Optional[QAReview] = None
    model_verification: Optional[ModelVerification] = None
    result: Optional[GenerateResponse] = None
