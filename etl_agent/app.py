"""Local account session and project-access API."""

import hmac
import ipaddress
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .db import PostgresStore, StoreUnavailable

COOKIE = "etl_session"


class LoginBody(BaseModel):
    username: str
    password: str


class Account(BaseModel):
    id: str
    username: str


class SessionOut(BaseModel):
    account: Account
    csrf_token: str


class Project(BaseModel):
    id: str
    name: str
    roles: list[str]


class ProjectList(BaseModel):
    items: list[Project]
    next_cursor: str | None


class ConnectionFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: Literal["mysql_source", "doris_target"] | None = None
    host: str | None = Field(default=None, min_length=1, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("name", "database_name")
    @classmethod
    def safe_text(cls, value):
        if value is not None and (not value.strip() or any(ord(char) < 32 for char in value)):
            raise ValueError("Invalid connection field")
        return value.strip() if value is not None else None

    @field_validator("host")
    @classmethod
    def valid_host(cls, value):
        if value is None:
            return None
        try:
            ipaddress.ip_address(value)
        except ValueError:
            label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
            if not all(re.fullmatch(label, part) for part in value.split(".")):
                raise ValueError("Invalid host")
        return value


class ConnectionCreate(ConnectionFields):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["mysql_source", "doris_target"]
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=64)


class ConnectionOut(ConnectionCreate):
    id: str
    project_id: str
    state: Literal["draft_unready"]
    credential_alias_id: None
    missing_fields: list[str]
    created_at: datetime
    updated_at: datetime


class ConnectionList(BaseModel):
    items: list[ConnectionOut]
    next_cursor: str | None


class PipelineFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_connection_id: UUID | None = None
    target_connection_id: UUID | None = None
    order_table: str | None = Field(default=None, min_length=1, max_length=128)
    user_table: str | None = Field(default=None, min_length=1, max_length=128)
    cycle_description: str | None = Field(default=None, min_length=1, max_length=240)

    @field_validator("order_table", "user_table", "cycle_description")
    @classmethod
    def safe_text(cls, value):
        if value is not None and (not value.strip() or any(ord(char) < 32 for char in value)):
            raise ValueError("Invalid pipeline field")
        return value.strip() if value is not None else None


class PipelineCreate(PipelineFields):
    source_connection_id: UUID
    target_connection_id: UUID
    order_table: str = Field(min_length=1, max_length=128)
    user_table: str = Field(min_length=1, max_length=128)
    cycle_description: str = Field(min_length=1, max_length=240)


class PipelineOut(PipelineCreate):
    id: str
    project_id: str
    state: Literal["draft_unready"]
    revision: int
    proposed_quality_thresholds: None
    proposed_runtime_budget: None
    created_at: datetime
    updated_at: datetime


class AuditEvent(BaseModel):
    id: str
    project_id: str
    actor_id: str
    action: Literal["connection.created", "connection.updated"]
    resource_id: str
    request_id: str
    created_at: datetime


class AuditEventList(BaseModel):
    items: list[AuditEvent]
    next_cursor: str | None


class AccessOut(BaseModel):
    project: Project


class DraftOverview(BaseModel):
    draft_unready_count: int
    href: str


class WorkbenchOut(BaseModel):
    project: Project
    allowed_actions: list[str]
    connections: DraftOverview | None
    unavailable_sections: list[Literal["pipelines", "preparations", "runs", "inbox"]]


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    resource_ref: str | None
    retryable: bool


class ErrorOut(BaseModel):
    error: ErrorDetail


ERRORS = {code: {"model": ErrorOut, "description": description} for code, description in {
    400: "Invalid request or HTTPS required",
    401: "Authentication required or credentials rejected",
    403: "Origin or CSRF rejected",
    404: "Project unavailable",
    422: "Business gate blocked",
    503: "Database unavailable",
}.items()}


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _error_body(code: str, message: str, retryable: bool = False):
    return {"error": {"code": code, "message": message, "request_id": str(uuid4()), "resource_ref": None, "retryable": retryable}}


def create_app(store=None, clock=None) -> FastAPI:
    store = store or PostgresStore()
    clock = clock or (lambda: datetime.now(timezone.utc))
    app = FastAPI(title="ETL-Agent API", version="0.1.0")

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        if request.url.path.startswith("/api/v1/") and request.url.scheme != "https":
            return JSONResponse(status_code=400, content=_error_body("HTTPS_REQUIRED", "HTTPS required"), headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "REQUEST_REJECTED", "message": "Request rejected"}
        return JSONResponse(status_code=exc.status_code, content=_error_body(detail["code"], detail["message"]))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content=_error_body("INVALID_REQUEST", "Invalid request"),
        )

    @app.exception_handler(StoreUnavailable)
    async def dependency_error(request: Request, exc: StoreUnavailable):
        return JSONResponse(
            status_code=503,
            content=_error_body("DEPENDENCY_UNAVAILABLE", "Service temporarily unavailable", retryable=True),
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=_error_body("INTERNAL_ERROR", "Internal error"),
        )

    def check_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host', '')}":
            raise _error(403, "ORIGIN_FORBIDDEN", "Request origin rejected")

    def current_session(cookie: str | None = Cookie(default=None, alias=COOKIE)):
        session = store.session(cookie, clock()) if cookie else None
        if not session:
            raise _error(401, "SESSION_EXPIRED", "Sign in required")
        return session

    def csrf_session(request: Request, x_csrf_token: str | None = Header(default=None), session=Depends(current_session)):
        check_origin(request)
        if not hmac.compare_digest(x_csrf_token or "", session["csrf_token"]):
            raise _error(403, "CSRF_REJECTED", "CSRF token rejected")
        return session

    def project_member(project_id: str, session=Depends(current_session)):
        project = store.project_access(session["id"], project_id)
        if not project:
            raise _error(404, "PROJECT_FORBIDDEN", "Project unavailable")
        return project

    def project_maker(project=Depends(project_member)):
        if "Maker" not in project["roles"]:
            raise _error(403, "ROLE_FORBIDDEN", "Operation not permitted")
        return project

    def project_auditor(project=Depends(project_member)):
        if "Auditor" not in project["roles"]:
            raise _error(403, "ROLE_FORBIDDEN", "Operation not permitted")
        return project

    @app.post("/api/v1/session", response_model=SessionOut, responses={code: ERRORS[code] for code in (400, 401, 403, 503)})
    def login(body: LoginBody, request: Request, response: Response):
        check_origin(request)
        result = store.login(body.username, body.password, clock(), request.cookies.get(COOKIE))
        if not result:
            raise _error(401, "INVALID_CREDENTIALS", "Invalid credentials")
        response.set_cookie(COOKIE, result.pop("cookie"), httponly=True, secure=True, samesite="lax", path="/api/v1")
        return {"account": {"id": result["id"], "username": result["username"]}, "csrf_token": result["csrf_token"]}

    @app.get("/api/v1/session", response_model=SessionOut, responses={code: ERRORS[code] for code in (401, 503)})
    def get_session(session=Depends(current_session)):
        return {"account": {"id": session["id"], "username": session["username"]}, "csrf_token": session["csrf_token"]}

    @app.delete("/api/v1/session", status_code=204, responses={code: ERRORS[code] for code in (401, 403, 503)})
    def logout(request: Request, response: Response, session=Depends(csrf_session)):
        store.logout(request.cookies[COOKIE])
        response.delete_cookie(COOKIE, path="/api/v1", secure=True, httponly=True, samesite="lax")

    @app.get("/api/v1/projects", response_model=ProjectList, responses={code: ERRORS[code] for code in (401, 503)})
    def projects(session=Depends(current_session)):
        return {"items": store.projects(session["id"]), "next_cursor": None}

    @app.get("/api/v1/projects/{project_id}/access", response_model=AccessOut, responses={code: ERRORS[code] for code in (401, 404, 503)})
    def access(project=Depends(project_member)):
        return {"project": project}

    @app.get("/api/v1/projects/{project_id}/workbench", response_model=WorkbenchOut, responses={code: ERRORS[code] for code in (401, 404, 503)})
    def workbench(project_id: str, session=Depends(current_session)):
        overview = store.workbench(session["id"], project_id)
        if not overview:
            raise _error(404, "PROJECT_FORBIDDEN", "Project unavailable")
        maker = "Maker" in overview["project"]["roles"]
        return {
            "project": overview["project"],
            "allowed_actions": ["project.read", "workbench.read"] + (["connections.read", "connections.create", "connections.update"] if maker else []) + (["audit_events.read"] if "Auditor" in overview["project"]["roles"] else []),
            "connections": {"draft_unready_count": overview["draft_unready_count"], "href": f"/api/v1/projects/{project_id}/connections"} if maker else None,
            "unavailable_sections": ["pipelines", "preparations", "runs", "inbox"],
        }

    @app.post("/api/v1/projects/{project_id}/connections", status_code=201, response_model=ConnectionOut, responses={code: ERRORS[code] for code in (400, 401, 403, 404, 503)})
    def create_connection(project_id: str, body: ConnectionCreate, response: Response, session=Depends(csrf_session), project=Depends(project_maker)):
        request_id = str(uuid4())
        result = store.create_connection(session["id"], project_id, body.model_dump(), request_id, clock())
        if not result:
            raise _error(404, "PROJECT_FORBIDDEN", "Project unavailable")
        response.headers["X-Request-ID"] = request_id
        response.headers["Location"] = f"/api/v1/projects/{project_id}/connections/{result['id']}"
        return result

    @app.get("/api/v1/projects/{project_id}/connections", response_model=ConnectionList, responses={code: ERRORS[code] for code in (400, 401, 403, 404, 503)})
    def list_connections(project_id: str, cursor: UUID | None = None, session=Depends(current_session), project=Depends(project_maker)):
        result = store.list_connections(session["id"], project_id, cursor)
        if result is None:
            raise _error(404, "PROJECT_FORBIDDEN", "Project unavailable")
        return result

    @app.get("/api/v1/projects/{project_id}/connections/{connection_id}", response_model=ConnectionOut, responses={code: ERRORS[code] for code in (400, 401, 403, 404, 503)})
    def get_connection(project_id: str, connection_id: UUID, session=Depends(current_session), project=Depends(project_maker)):
        result = store.get_connection(session["id"], project_id, connection_id)
        if not result:
            raise _error(404, "PROJECT_FORBIDDEN", "Connection unavailable")
        return result

    @app.patch("/api/v1/projects/{project_id}/connections/{connection_id}", response_model=ConnectionOut, responses={code: ERRORS[code] for code in (400, 401, 403, 404, 503)})
    def patch_connection(project_id: str, connection_id: UUID, body: ConnectionFields, response: Response, session=Depends(csrf_session), project=Depends(project_maker)):
        fields = body.model_dump(exclude_unset=True)
        if not fields or any(value is None for value in fields.values()):
            raise _error(400, "INVALID_REQUEST", "Invalid request")
        request_id = str(uuid4())
        result = store.update_connection(session["id"], project_id, connection_id, fields, request_id, clock())
        if not result:
            raise _error(404, "PROJECT_FORBIDDEN", "Connection unavailable")
        response.headers["X-Request-ID"] = request_id
        return result

    @app.post("/api/v1/projects/{project_id}/connections/{connection_id}/probes", status_code=422, response_model=ErrorOut, responses={code: ERRORS[code] for code in (400, 401, 403, 404, 503)})
    def block_probe(project_id: str, connection_id: UUID, session=Depends(csrf_session), project=Depends(project_maker)):
        if not store.get_connection(session["id"], project_id, connection_id):
            raise _error(404, "PROJECT_FORBIDDEN", "Connection unavailable")
        raise _error(422, "SECRET_ALIAS_UNAVAILABLE", "Credential alias required before probe")

    @app.post("/api/v1/projects/{project_id}/pipelines", status_code=201, response_model=PipelineOut, responses={code: ERRORS[code] for code in (400, 401, 403, 404, 503)})
    def create_pipeline(project_id: str, body: PipelineCreate, response: Response, session=Depends(csrf_session), project=Depends(project_maker)):
        request_id = str(uuid4())
        result = store.create_pipeline(session["id"], project_id, body.model_dump(), request_id, clock())
        if not result:
            raise _error(404, "PROJECT_FORBIDDEN", "Pipeline connections unavailable")
        response.headers["X-Request-ID"] = request_id
        response.headers["Location"] = f"/api/v1/projects/{project_id}/pipelines/{result['id']}"
        return result

    @app.get("/api/v1/projects/{project_id}/pipelines/{pipeline_id}", response_model=PipelineOut, responses={code: ERRORS[code] for code in (400, 401, 403, 404, 503)})
    def get_pipeline(project_id: str, pipeline_id: UUID, session=Depends(current_session), project=Depends(project_maker)):
        result = store.get_pipeline(session["id"], project_id, pipeline_id)
        if not result:
            raise _error(404, "PROJECT_FORBIDDEN", "Pipeline unavailable")
        return result

    @app.patch("/api/v1/projects/{project_id}/pipelines/{pipeline_id}", response_model=PipelineOut, responses={code: ERRORS[code] for code in (400, 401, 403, 404, 503)})
    def patch_pipeline(project_id: str, pipeline_id: UUID, body: PipelineFields, response: Response, session=Depends(csrf_session), project=Depends(project_maker)):
        fields = body.model_dump(exclude_unset=True)
        if not fields or any(value is None for value in fields.values()):
            raise _error(400, "INVALID_REQUEST", "Invalid request")
        request_id = str(uuid4())
        result = store.update_pipeline(session["id"], project_id, pipeline_id, fields, request_id, clock())
        if not result:
            raise _error(404, "PROJECT_FORBIDDEN", "Pipeline or connections unavailable")
        response.headers["X-Request-ID"] = request_id
        return result

    @app.get("/api/v1/projects/{project_id}/audit-events", response_model=AuditEventList, responses={code: ERRORS[code] for code in (400, 401, 403, 404, 503)})
    def audit_events(project_id: str, cursor: UUID | None = None, action: Literal["connection.created", "connection.updated"] | None = None, actor_id: UUID | None = None, session=Depends(current_session), project=Depends(project_auditor)):
        try:
            result = store.list_audit_events(session["id"], project_id, cursor, action, actor_id)
        except ValueError:
            raise _error(400, "INVALID_REQUEST", "Invalid cursor")
        if result is None:
            raise _error(404, "PROJECT_FORBIDDEN", "Project unavailable")
        return result

    def openapi():
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            for path, methods in schema["paths"].items():
                if path.startswith("/api/v1/"):
                    for operation in methods.values():
                        if not path.endswith("/probes") and "422" in operation["responses"]:
                            del operation["responses"]["422"]
                        operation["responses"].setdefault("400", {"description": "Invalid request or HTTPS required", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorOut"}}}})
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi
    return app


app = create_app()
