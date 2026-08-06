# ruff: noqa: E501
import json
from datetime import UTC, datetime
from decimal import Decimal
from html import escape
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.api.auth import browser_account
from app.api.auth import router as auth_router
from app.api.v1.router import router
from app.core.config import get_settings
from app.db.session import get_db
from app.models import (
    AccessGrant,
    AIIntakeRequest,
    CandidateRecord,
    Person,
    ProcessingRun,
    ProposedHealthFact,
    ProposedHealthFactGroup,
    SourceArtifact,
    SourceSystem,
    UserAccount,
    ValidationIssue,
)
from app.models.enums import AccountStatus
from app.repositories.observations import query_observations
from app.services.auth import Actor
from app.services.authorization import Action, AuthorizationError, authorize

settings = get_settings()
DB = Annotated[Session, Depends(get_db)]
app = FastAPI(
    title="Health Avatar API",
    version=__version__,
    description="Privacy-first longitudinal health data platform. Not medical advice.",
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[host.strip() for host in settings.allowed_hosts.split(",") if host.strip()],
)
app.include_router(auth_router)
app.include_router(router)

STYLE = "body{font:16px system-ui;margin:0;color:#15202b}main{max-width:60rem;margin:auto;padding:1rem}nav{background:#123b57;color:white;padding:1rem}nav a{color:white}a,button{min-height:44px}table{width:100%;border-collapse:collapse}td,th{padding:.6rem;border-bottom:1px solid #ddd;text-align:left}.card{padding:1rem;margin:.7rem 0;border:1px solid #ccd;border-radius:.5rem}.warning{color:#9b2c2c}@media(max-width:600px){table{font-size:.88rem}.optional{display:none}}"
SCRIPT = "<script>function csrf(){return document.cookie.split('; ').find(x=>x.startsWith('health_avatar_csrf='))?.split('=')[1]||''}async function submitForm(e){e.preventDefault();let h={'X-CSRF-Token':decodeURIComponent(csrf())};let r=await fetch(e.target.action,{method:e.target.method,body:new FormData(e.target),headers:h});if(!r.ok){alert(await r.text());return}let j=await r.json();if(e.target.action.endsWith('/artifacts')){let p=await fetch('/api/v1/artifacts/'+j.id+'/process',{method:'POST',headers:h});if(!p.ok){alert(await p.text());return}let run=await p.json();location.href='/app/processing-runs/'+run.id}else if(j.processing_run_id){location.href='/app/ai-intake/'+j.id}else{location.href='/app'}}async function intakeText(e){e.preventDefault();let f=new FormData(e.target);let b={text:f.get('text'),purpose:f.get('purpose'),sensitivity:f.get('sensitivity'),consent:f.get('consent')==='on'};let r=await fetch(e.target.action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf())},body:JSON.stringify(b)});if(!r.ok){alert(await r.text());return}let j=await r.json();location.href='/app/ai-intake/'+j.id}async function action(url,body){let r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf())},body:JSON.stringify(body||{})});if(r.ok)location.reload();else alert(await r.text())}</script>"


def page(title: str, body: str) -> str:
    banner = (
        "<p class='warning'>Development authentication enabled — unsafe for production.</p>"
        if settings.development_auth_enabled
        else ""
    )
    return f"<!doctype html><html><meta name='viewport' content='width=device-width'><title>{escape(title)}</title><style>{STYLE}</style><nav><a href='/app'>Health Avatar</a></nav><main>{banner}{body}</main>{SCRIPT}</html>"


def active_browser_account(request: Request, session: Session) -> UserAccount | RedirectResponse:
    account = browser_account(request, session)
    if account is None:
        return RedirectResponse("/auth/login", status_code=303)
    if account.account_status == AccountStatus.PENDING:
        return RedirectResponse("/pending", status_code=303)
    if not account.is_active or account.account_status != AccountStatus.ACTIVE:
        return RedirectResponse("/auth/login", status_code=303)
    return account


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/", include_in_schema=False)
def root(request: Request, session: DB) -> RedirectResponse:
    return RedirectResponse(
        "/app" if browser_account(request, session) else "/auth/login", status_code=303
    )


@app.get("/pending", response_class=HTMLResponse, response_model=None, include_in_schema=False)
def pending(request: Request, session: DB) -> HTMLResponse | RedirectResponse:
    account = browser_account(request, session)
    if account is None:
        return RedirectResponse("/auth/login", status_code=303)
    if account.is_active and account.account_status == AccountStatus.ACTIVE:
        return RedirectResponse("/app", status_code=303)
    if account.account_status != AccountStatus.PENDING:
        return RedirectResponse("/auth/login", status_code=303)
    return HTMLResponse(
        page(
            "Access pending",
            f"<h1>Access pending</h1><p>Authentication succeeded for {escape(account.display_name)}, but no health-data access has been activated. An administrator must activate the account and create an explicit person grant.</p>",
        )
    )


@app.get("/app", response_class=HTMLResponse, response_model=None, include_in_schema=False)
def person_selector(request: Request, session: DB) -> HTMLResponse | RedirectResponse:
    account = active_browser_account(request, session)
    if isinstance(account, RedirectResponse):
        return account
    now = datetime.now(UTC)
    persons = session.scalars(
        select(Person)
        .join(AccessGrant)
        .where(
            AccessGrant.user_account_id == account.id,
            AccessGrant.revoked_at.is_(None),
            or_(AccessGrant.expires_at.is_(None), AccessGrant.expires_at > now),
        )
        .order_by(Person.preferred_name, Person.id)
    )
    cards = "".join(
        f"<div class='card'><a href='/app/persons/{person.id}'>{escape(person.preferred_name)}</a></div>"
        for person in persons
    )
    return HTMLResponse(
        page("Your people", f"<h1>Your people</h1>{cards or '<p>No active person grants.</p>'}")
    )


@app.get(
    "/app/persons/{person_id}",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
def person_summary(
    person_id: UUID, request: Request, session: DB
) -> HTMLResponse | RedirectResponse:
    account = active_browser_account(request, session)
    if isinstance(account, RedirectResponse):
        return account
    try:
        authorize(
            session, Actor(account.id, account.is_system_administrator), person_id, Action.VIEW
        )
    except AuthorizationError as exc:
        raise HTTPException(
            404, detail={"code": "not_found", "message": "Resource not found"}
        ) from exc
    person = session.get(Person, person_id)
    if person is None:
        raise HTTPException(404)
    observations = list(session.scalars(query_observations(session, person_id=person_id).limit(10)))
    artifacts = list(
        session.scalars(
            select(SourceArtifact)
            .where(SourceArtifact.subject_person_id == person_id)
            .order_by(SourceArtifact.received_at.desc(), SourceArtifact.id)
            .limit(10)
        )
    )
    obs_html = "".join(
        f"<tr><td>{escape(item.observation_type.display_name)}</td><td>{escape(str(item.numeric_value or item.text_value or item.boolean_value))}</td><td>{escape(item.unit or '')}</td><td>{escape(item.observed_at.isoformat())}</td></tr>"
        for item in observations
    )
    runs_html = "".join(
        f"<li>{escape(item.original_filename or item.artifact_kind)} — {escape(item.processing_status)}</li>"
        for item in artifacts
    )
    review_links: list[str] = []
    for artifact in artifacts:
        latest_run = session.scalar(
            select(ProcessingRun)
            .where(ProcessingRun.source_artifact_id == artifact.id)
            .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id)
        )
        if latest_run is not None:
            review_links.append(
                f"<li><a href='/app/processing-runs/{latest_run.id}'>Review {escape(artifact.original_filename or artifact.artifact_kind)}</a></li>"
            )
    intakes = session.scalars(
        select(AIIntakeRequest)
        .where(AIIntakeRequest.person_id == person_id)
        .order_by(AIIntakeRequest.created_at.desc(), AIIntakeRequest.id)
        .limit(10)
    )
    intake_html = "".join(
        f"<li><a href='/app/ai-intake/{item.id}'>{escape(item.intake_purpose)}</a> — {escape(item.status)}</li>"
        for item in intakes
    )
    body = f"<h1>{escape(person.preferred_name)}</h1><p><a href='/app/persons/{person.id}/add-health'>Add health information</a> · <a href='/app/persons/{person.id}/workout-photo'>Add workout from photo</a> · <a href='/app/persons/{person.id}/upload'>Upload canonical CSV</a></p><h2>Recent observations</h2><table><tr><th>Type</th><th>Value</th><th>Unit</th><th class='optional'>Observed</th></tr>{obs_html}</table><h2>Recent AI intake</h2><ul>{intake_html or '<li>None yet</li>'}</ul><h2>Recent ingestion</h2><ul>{runs_html}</ul><h2>Review staged records</h2><ul>{''.join(review_links)}</ul>"
    return HTMLResponse(page(person.preferred_name, body))


def _intake_form_account(
    person_id: UUID, request: Request, session: Session
) -> UserAccount | RedirectResponse:
    account = active_browser_account(request, session)
    if isinstance(account, RedirectResponse):
        return account
    try:
        authorize(
            session, Actor(account.id, account.is_system_administrator), person_id, Action.SUBMIT
        )
    except AuthorizationError as exc:
        raise HTTPException(404) from exc
    return account


@app.get(
    "/app/persons/{person_id}/add-health",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
def add_health_page(
    person_id: UUID, request: Request, session: DB
) -> HTMLResponse | RedirectResponse:
    account = _intake_form_account(person_id, request, session)
    if isinstance(account, RedirectResponse):
        return account
    disclosure = escape(f"Provider: {settings.ai_provider}; model: configured by the server")
    body = f"<h1>Add health information</h1><p>Type or dictate health information. Extracted values are proposals until you review and confirm them. This service does not diagnose or advise treatment.</p><form onsubmit='intakeText(event)' action='/api/v1/persons/{person_id}/ai-intake/text' method='post'><label>Information<textarea name='text' rows='7' required></textarea></label><br><label>Category hint<select name='purpose'><option>general_health</option><option>exercise</option><option>laboratory</option><option>nutrition</option><option>medication</option><option>symptom</option><option>other</option></select></label><input type='hidden' name='sensitivity' value='general_health'><div class='card'><strong>Processing consent</strong><p>{disclosure}. Health-related content will be processed for structured extraction. You must review every fact.</p><label><input type='checkbox' name='consent' required> I consent to this processing.</label></div><button>Extract proposed facts</button></form>"
    return HTMLResponse(page("Add health information", body))


@app.get(
    "/app/persons/{person_id}/workout-photo",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
def workout_photo_page(
    person_id: UUID, request: Request, session: DB
) -> HTMLResponse | RedirectResponse:
    account = _intake_form_account(person_id, request, session)
    if isinstance(account, RedirectResponse):
        return account
    body = f"<h1>Add workout from photo</h1><p>The original image remains private. A metadata-stripped safe representation is sent to the configured provider. Every extracted metric requires review.</p><form onsubmit='submitForm(event)' action='/api/v1/persons/{person_id}/ai-intake/image' method='post' enctype='multipart/form-data'><input type='hidden' name='purpose' value='exercise'><input type='hidden' name='sensitivity' value='exercise'><label>Workout image<input type='file' name='file' accept='image/jpeg,image/png,image/webp' required></label><br><label>Optional context<input name='context' maxlength='2000' placeholder='Elliptical workout'></label><div class='card'><strong>Processing consent</strong><p>Provider: {escape(settings.ai_provider)}. Health-related image content will be transmitted when a cloud provider is enabled.</p><label><input type='checkbox' name='consent' required> I consent and will review all extracted facts.</label></div><button>Extract workout</button></form>"
    return HTMLResponse(page("Add workout from photo", body))


@app.get(
    "/app/ai-intake/{intake_id}",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
def ai_intake_review_page(
    intake_id: UUID, request: Request, session: DB
) -> HTMLResponse | RedirectResponse:
    account = active_browser_account(request, session)
    if isinstance(account, RedirectResponse):
        return account
    intake = session.get(AIIntakeRequest, intake_id)
    if intake is None or intake.processing_run_id is None:
        raise HTTPException(404)
    try:
        authorize(
            session,
            Actor(account.id, account.is_system_administrator),
            intake.person_id,
            Action.VIEW,
        )
    except AuthorizationError as exc:
        raise HTTPException(404) from exc
    groups = {
        group.id: group
        for group in session.scalars(
            select(ProposedHealthFactGroup).where(
                ProposedHealthFactGroup.processing_run_id == intake.processing_run_id
            )
        )
    }
    facts = list(
        session.scalars(
            select(ProposedHealthFact)
            .where(ProposedHealthFact.processing_run_id == intake.processing_run_id)
            .order_by(ProposedHealthFact.created_at, ProposedHealthFact.id)
        )
    )
    sections: dict[str, list[ProposedHealthFact]] = {}
    for fact in facts:
        label = (
            groups[fact.fact_group_id].display_name
            if fact.fact_group_id in groups
            else "Other facts"
        )
        sections.setdefault(label, []).append(fact)
    section_html = ""
    for label, items in sections.items():
        rows = ""
        for fact in items:
            value = fact.numeric_value if fact.numeric_value is not None else fact.text_value
            confidence = f"{float(fact.confidence or 0):.0%}"
            low = (
                " — low confidence"
                if fact.confidence is not None and fact.confidence < Decimal("0.8")
                else ""
            )
            rows += f"<tr><td>{escape(fact.display_name)}</td><td>{escape(str(value or 'unresolved'))}</td><td>{escape(fact.unit or '')}</td><td>{escape(fact.canonical_status)}</td><td>{confidence}{low}</td></tr>"
        section_html += f"<section class='card'><h2>{escape(label)}</h2><table><tr><th>Proposed fact</th><th>Value</th><th>Unit</th><th>Status</th><th>Confidence</th></tr>{rows}</table></section>"
    unsupported = sum(fact.canonical_status in {"unsupported", "unresolved"} for fact in facts)
    body = f"<h1>Review extracted health facts</h1><p><strong>Not confirmed:</strong> these values are AI proposals. No diagnosis or treatment advice is provided.</p><p>Status: {escape(intake.status)}; provider: {escape(intake.provider_name)}; model: {escape(intake.model_name)}; prompt {escape(intake.prompt_version)}.</p>{section_html}<p>Unsupported or unresolved facts: {unsupported}. They remain staged and are not forced into canonical records.</p><button onclick=\"action('/api/v1/ai-intake/{intake.id}/confirm')\">Confirm supported facts</button> <button onclick=\"action('/api/v1/ai-intake/{intake.id}/reject',{{reason:'Rejected in review'}})\">Reject submission</button>"
    return HTMLResponse(page("Review extracted health facts", body))


@app.get(
    "/app/persons/{person_id}/upload",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
def upload_page(person_id: UUID, request: Request, session: DB) -> HTMLResponse | RedirectResponse:
    account = active_browser_account(request, session)
    if isinstance(account, RedirectResponse):
        return account
    try:
        authorize(
            session, Actor(account.id, account.is_system_administrator), person_id, Action.SUBMIT
        )
    except AuthorizationError as exc:
        raise HTTPException(404) from exc
    sources = session.scalars(select(SourceSystem).order_by(SourceSystem.name, SourceSystem.id))
    options = "".join(
        f"<option value='{source.id}'>{escape(source.name)}</option>" for source in sources
    )
    body = f"<h1>Upload artifact</h1><form onsubmit='submitForm(event)' action='/api/v1/artifacts' method='post' enctype='multipart/form-data'><input type='hidden' name='person_id' value='{person_id}'><label>Source system<select name='source_system_id' required>{options}</select></label><br><label>Canonical CSV<input type='file' name='file' accept='.csv,text/csv' required></label><br><label>Captured date<input type='datetime-local' name='captured_at'></label><br><button>Upload</button></form>"
    return HTMLResponse(page("Upload artifact", body))


@app.get(
    "/app/processing-runs/{run_id}",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
def processing_page(run_id: UUID, request: Request, session: DB) -> HTMLResponse | RedirectResponse:
    account = active_browser_account(request, session)
    if isinstance(account, RedirectResponse):
        return account
    run = session.get(ProcessingRun, run_id)
    artifact = session.get(SourceArtifact, run.source_artifact_id) if run else None
    if run is None or artifact is None or artifact.subject_person_id is None:
        raise HTTPException(404)
    try:
        authorize(
            session,
            Actor(account.id, account.is_system_administrator),
            artifact.subject_person_id,
            Action.VIEW,
        )
    except AuthorizationError as exc:
        raise HTTPException(404) from exc
    issues = session.scalars(
        select(ValidationIssue)
        .where(ValidationIssue.processing_run_id == run.id)
        .order_by(ValidationIssue.created_at, ValidationIssue.id)
    )
    candidates = session.scalars(
        select(CandidateRecord)
        .where(CandidateRecord.processing_run_id == run.id)
        .order_by(CandidateRecord.created_at, CandidateRecord.id)
    )
    issue_html = "".join(
        f"<li>{escape(issue.source_locator or '')}: {escape(issue.message)}</li>"
        for issue in issues
    )
    candidate_html = "".join(
        f"<tr><td>{escape(candidate.source_locator)}</td><td>{escape(candidate.candidate_type)}</td><td><code>{escape(json.dumps(candidate.normalized_candidate_json or {}, sort_keys=True))}</code></td><td>{escape(candidate.status)}</td><td><button onclick=\"action('/api/v1/candidates/{candidate.id}/approve')\">Approve</button> <button onclick=\"action('/api/v1/candidates/{candidate.id}/reject',{{reason:'Rejected in review'}})\">Reject</button></td></tr>"
        for candidate in candidates
    )
    body = f"<h1>Processing run</h1><p>Status: {escape(run.status)}; adapter: {escape(run.adapter_name)} {escape(run.adapter_version)}</p><p>Candidates {run.candidate_count}; promoted {run.accepted_count}; rejected {run.rejected_count}; review {run.review_required_count}</p><h2>Validation issues</h2><ul>{issue_html}</ul><h2>Candidates</h2><table><tr><th>Source</th><th>Type</th><th>Values</th><th>Status</th><th>Review</th></tr>{candidate_html}</table>"
    return HTMLResponse(page("Processing run", body))


@app.exception_handler(Exception)
async def unhandled_error(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Internal server error"}},
    )


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    error = (
        detail
        if isinstance(detail, dict) and "code" in detail
        else {"code": "http_error", "message": str(detail)}
    )
    return JSONResponse(status_code=exc.status_code, content={"error": error})


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": exc.errors(),
            }
        },
    )
