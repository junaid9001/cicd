import io
import zipfile
from pathlib import Path
from typing import Dict, List

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .analyzer import analyze_repo
from .auth import create_access_token, get_current_user, hash_password, verify_password
from .billing import parse_subscription_event, stripe_secret, verify_stripe_signature
from .cicd import generate_cicd_files
from .db import (
    create_user,
    get_subscription,
    get_user_by_email,
    init_db,
    link_customer_to_tenant,
    list_recent,
    save_analysis,
    update_subscription_by_customer,
)
from .github_client import GitHubError, fetch_repo_data
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AuthResponse,
    GeneratedFile,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    StripeWebhookResponse,
)


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"

app = FastAPI(title="Repo2CI SaaS", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/analyses")
def analyses(limit: int = 10, user: Dict[str, object] = Depends(get_current_user)) -> List[Dict[str, object]]:
    data = list_recent(tenant_id=int(user["tenant_id"]), limit=min(max(limit, 1), 50))
    return [item.model_dump(mode="json") for item in data]


def _build_analysis(payload: AnalyzeRequest, user: Dict[str, object]) -> AnalyzeResponse:
    try:
        repo_data = fetch_repo_data(str(payload.repo_url), payload.branch)
        profile = analyze_repo(repo_data)
        generated = generate_cicd_files(
            repository=repo_data.slug,
            profile=profile,
            include_deploy=payload.include_deploy,
            include_security=payload.include_security,
            ci_provider=payload.ci_provider,
        )
    except GitHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}") from exc

    save_analysis(
        tenant_id=int(user["tenant_id"]),
        user_id=int(user["id"]),
        repo_url=str(payload.repo_url),
        ci_provider=payload.ci_provider,
        profile=profile.model_dump(mode="json"),
        files=generated,
    )

    recommendations = [
        "Protect main branch with required status checks.",
        "Require code owners review for critical folders.",
        "Pin action versions and dependencies for deterministic builds.",
    ]
    if not profile.has_dockerfile:
        recommendations.append("Add a Dockerfile to standardize build and runtime environments.")

    files = [GeneratedFile(path=path, content=content) for path, content in generated.items()]

    return AnalyzeResponse(
        repository=repo_data.slug,
        branch=repo_data.default_branch,
        ci_provider=payload.ci_provider,
        profile=profile,
        files=files,
        recommendations=recommendations,
    )


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest, user: Dict[str, object] = Depends(get_current_user)) -> AnalyzeResponse:
    return _build_analysis(payload, user)


@app.post("/api/analyze/zip")
def analyze_zip(payload: AnalyzeRequest, user: Dict[str, object] = Depends(get_current_user)) -> StreamingResponse:
    result = _build_analysis(payload, user)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in result.files:
            zf.writestr(item.path, item.content)
    archive.seek(0)
    repo_name = result.repository.replace("/", "-")
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{repo_name}-{result.ci_provider}-cicd.zip"'},
    )


@app.post("/api/auth/register", response_model=AuthResponse)
def register(payload: RegisterRequest) -> AuthResponse:
    if "@" not in payload.email:
        raise HTTPException(status_code=400, detail="Invalid email format")
    try:
        user = create_user(company=payload.company, email=payload.email, password_hash=hash_password(payload.password))
    except ValueError as exc:
        if str(exc) == "EMAIL_EXISTS":
            raise HTTPException(status_code=409, detail="Email already exists") from exc
        raise HTTPException(status_code=400, detail="Invalid signup data") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Signup failed: {exc}") from exc
    token = create_access_token(user_id=int(user["id"]), tenant_id=int(user["tenant_id"]), email=str(user["email"]))
    return AuthResponse(access_token=token)


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    if "@" not in payload.email:
        raise HTTPException(status_code=400, detail="Invalid email format")
    user = get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, str(user["password_hash"])):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user_id=int(user["id"]), tenant_id=int(user["tenant_id"]), email=str(user["email"]))
    return AuthResponse(access_token=token)


@app.get("/api/auth/me", response_model=MeResponse)
def me(user: Dict[str, object] = Depends(get_current_user)) -> MeResponse:
    return MeResponse(user_id=int(user["id"]), email=str(user["email"]), tenant_id=int(user["tenant_id"]), company=str(user["company"]))


@app.get("/api/billing/subscription")
def subscription(user: Dict[str, object] = Depends(get_current_user)) -> Dict[str, object]:
    return get_subscription(int(user["tenant_id"]))


@app.post("/api/billing/link-customer")
def link_customer(customer_id: str, user: Dict[str, object] = Depends(get_current_user)) -> Dict[str, bool]:
    link_customer_to_tenant(int(user["tenant_id"]), customer_id)
    return {"linked": True}


@app.post("/api/billing/webhook", response_model=StripeWebhookResponse)
async def stripe_webhook(request: Request, stripe_signature: str = Header(default="", alias="Stripe-Signature")) -> StripeWebhookResponse:
    body = await request.body()
    secret = stripe_secret()
    if secret and not verify_stripe_signature(payload=body, signature_header=stripe_signature, secret=secret):
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    event_type, obj = parse_subscription_event(body if body else b"{}")
    if event_type.startswith("customer.subscription."):
        customer = str(obj.get("customer", ""))
        subscription_id = str(obj.get("id", ""))
        status = str(obj.get("status", "inactive"))
        plan_data = obj.get("plan", {})
        plan = "pro"
        if isinstance(plan_data, dict):
            plan = str(plan_data.get("nickname") or plan_data.get("id") or "pro")
        if customer:
            update_subscription_by_customer(customer, subscription_id, status, plan)
    return StripeWebhookResponse(received=True, event_type=event_type)


if WEB_DIR.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


@app.get("/")
def index() -> FileResponse:
    file_path = WEB_DIR / "index.html"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not built")
    return FileResponse(file_path)
