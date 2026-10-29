"""Errors as `application/problem+json` with stable codes, the same on both listeners."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from thursday_contracts.problems import PROBLEM_MEDIA_TYPE, Problem, ProblemCode

from thursday_gateway.application.devices import RateLimited
from thursday_gateway.application.errors import AgentRefused, AgentUnavailable
from thursday_gateway.application.projects import NotFound
from thursday_gateway.domain.model import InvalidInput, QueueFull

AGENT_CODES = {
    -32041: (409, ProblemCode.APPROVAL_ALREADY_RESOLVED),
    -32040: (409, ProblemCode.TASK_NOT_PAUSABLE),
    -32002: (409, ProblemCode.CONFLICT),
    -32001: (404, ProblemCode.NOT_FOUND),
    -32004: (409, ProblemCode.CONFLICT),
}


def problem(status: int, code: ProblemCode, title: str, detail: str = "") -> JSONResponse:
    body = Problem(title=title, status=status, code=code, detail=detail).model_dump(mode="json")
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return problem(404, ProblemCode.NOT_FOUND, "Not found", str(exc))

    @app.exception_handler(InvalidInput)
    async def invalid(_: Request, exc: InvalidInput) -> JSONResponse:
        return problem(422, ProblemCode.INVALID_INPUT, "Invalid input", str(exc))

    @app.exception_handler(RateLimited)
    async def limited(_: Request, exc: RateLimited) -> JSONResponse:
        response = problem(429, ProblemCode.RATE_LIMITED, "Too many attempts", str(exc))
        response.headers["Retry-After"] = "60"
        return response

    @app.exception_handler(QueueFull)
    async def queue_full(_: Request, exc: QueueFull) -> JSONResponse:
        response = problem(429, ProblemCode.RATE_LIMITED, "Too many waiting messages", str(exc))
        response.headers["Retry-After"] = "30"
        return response

    @app.exception_handler(AgentUnavailable)
    async def down(_: Request, exc: AgentUnavailable) -> JSONResponse:
        return problem(503, ProblemCode.DEPENDENCY_DOWN, "A service is unavailable", str(exc))

    @app.exception_handler(AgentRefused)
    async def refused(_: Request, exc: AgentRefused) -> JSONResponse:
        if 400 <= exc.code <= 599:  # an agent's own HTTP answer, passed through
            http_codes = {404: ProblemCode.NOT_FOUND, 422: ProblemCode.INVALID_INPUT, 503: ProblemCode.DEPENDENCY_DOWN}
            return problem(
                exc.code, http_codes.get(exc.code, ProblemCode.CONFLICT), "The agent refused the request", str(exc)
            )
        status, code = AGENT_CODES.get(exc.code, (502, ProblemCode.CONFLICT))
        return problem(status, code, "The agent refused the request", str(exc))
