from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl


class AnalyzeRequest(BaseModel):
    repo_url: HttpUrl
    branch: Optional[str] = None
    include_deploy: bool = True
    include_security: bool = True
    ci_provider: Literal["github", "gitlab", "jenkins"] = "github"


class TechProfile(BaseModel):
    primary_language: str
    languages: List[str]
    frameworks: List[str]
    package_managers: List[str]
    has_dockerfile: bool
    test_hints: List[str]


class GeneratedFile(BaseModel):
    path: str
    content: str


class AnalyzeResponse(BaseModel):
    repository: str
    branch: str
    ci_provider: Literal["github", "gitlab", "jenkins"]
    profile: TechProfile
    files: List[GeneratedFile]
    recommendations: List[str]


class AnalysisRecord(BaseModel):
    id: int
    tenant_id: int
    user_id: int
    repo_url: str
    ci_provider: str
    profile: Dict[str, object]
    files: Dict[str, str]
    created_at: datetime


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8)
    company: str = Field(..., min_length=2, max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    user_id: int
    email: str
    tenant_id: int
    company: str


class StripeWebhookResponse(BaseModel):
    received: bool
    event_type: str


class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Human-friendly error message")
