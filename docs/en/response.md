# Unified Response & Error Codes

To keep API contracts stable between backend and frontend, `fastapi_extra` provides a complete uniform response scheme:

- **`ResultEnum`**: 120+ predefined Aliyun-style status codes grouped as user errors (A), system errors (B) and third-party call errors (C).
- **`APIResult[T]`**: generic response envelope `{data: T}`, `APIResult.ok(data, ...)` returns an `APIResponse` ready for FastAPI.
- **`APIResponse`**: extends FastAPI's `JSONResponse`, uses Pydantic v2 native serializer with `by_alias=True` and defaults preserved.
- **`APIError`**: throwable exception with `code` + `message`, used to short-circuit the business layer and return conformant JSON.

---

## 1. Response shape

Every success / failure response uses the same JSON shape:

```json
{
  "code":    "00000",
  "message": "OK",
  "data":    ... /* generic T */
}
```

| Field | Meaning | Notes |
|-------|---------|-------|
| `code` | Result code | `"00000"` = success. Other codes come from `ResultEnum` or arbitrary string values you provide. |
| `message` | Result description | Default `"OK"` on success; on failure it carries a human-readable reason. |
| `data` | Response payload | Generic `T`. To keep the OpenAPI schema accurate, declare routes with return type `APIResult[T]`. |

> Note: The Pydantic model `APIResult` itself only declares a single `data` field. `code` / `message` are either produced by the global `APIError` handler or supplemented by your custom envelope model (see §6). For projects that want these three fields reflected in schema, we recommend declaring a custom `Envelope` model (see §6).

---

## 2. `APIResult[T]`: success responses

### 2.1 Basic usage

```python
from fastapi import FastAPI
from fastapi_extra.response import APIResult

app = FastAPI()

@app.get("/ping", response_model=APIResult[str])
async def ping() -> APIResult[str]:
    return APIResult.ok("pong")
```

HTTP response:

```json
{"data":"pong"}
```

(With a global handler that enriches with `code / message`, the response becomes `{"code":"00000","message":"OK","data":"pong"}` — see §5.)

### 2.2 Custom status code / headers

```python
@app.get("/resource", response_model=APIResult[dict])
async def resource() -> APIResult[dict]:
    return APIResult.ok(
        {"foo": "bar"},
        status_code=201,
        headers={"X-Trace-Id": "abcdef"},
    )
```

---

## 3. `ResultEnum`: the 120+ error-code dictionary

Each enum member stores a `(code, message)` tuple:

| Prefix | Range | Example |
|--------|-------|---------|
| A | Client error | `A0400` = "用户请求参数错误"; `A0111` = "用户名已存在"; `A0301` = "访问未授权" |
| B | Server error | `B0001` = "系统执行出错"; `B0100` = "系统执行超时"; `B0210` = "系统限流" |
| C | Third-party call error | `C0001` = "调用第三方服务出错"; `C0300` = "数据库服务出错"; `C0341` = "主键冲突" |
| 00000 / 99999 | Success / catch-all | `SUCCESS = ("00000","OK")`; `FAILED = ("99999","系统异常")` |

Usage:

```python
from fastapi_extra.response import ResultEnum

result = ResultEnum.A0301
code, msg = result.value           # => ("A0301", "访问未授权")
```

> Reference: the enumeration implements common entries from Aliyun's "API Gateway Error Code Specification" (user, login, permission, parameter, resource, upload, version, privacy, device, system, disaster recovery, middleware, database, notification, etc.). Domain-specific business codes not covered here can always be expressed as `APIError(code="…", message="…")` with a custom string.

---

## 4. `APIError`: business exceptions

```python
from fastapi_extra.response import APIError, ResultEnum

# (A) Predefined ResultEnum + optional custom message
raise APIError(ResultEnum.A0400, message="username must be between 2 and 32 characters")

# (B) Raw code / message strings
raise APIError(code="ORDER-001", message="Insufficient stock to place order")
```

`APIError` is a subclass of `Exception` with:

| Attribute / Method | Description |
|--------------------|-------------|
| `.code: str`       | Error code (from `ResultEnum` or custom). |
| `.message: str`    | Error message. |
| `str(err)`         | Returns the `message`. |
| `repr(err)`        | Returns `[CODE]message`, ideal for logs. |

---

## 5. Global exception handlers (recommended)

Translate all exceptions into the canonical `{code, message, data}` envelope:

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi_extra.response import APIError, ResultEnum

app = FastAPI()

@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "code":    exc.code,
            "message": exc.message,
            "data":    None,
        },
    )

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    code, _ = ResultEnum.A0400.value
    message = "; ".join(
        f"{' → '.join(map(str, err['loc']))}: {err['msg']}" for err in exc.errors()
    )
    return JSONResponse(
        status_code=200,
        content={"code": code, "message": message, "data": None},
    )
```

Now callers parse **business errors** and **validation errors** with exactly the same structure, reducing the number of frontend `try / except` branches.

---

## 6. Optional: full `Envelope` schema

To expose all three `code / message / data` fields directly in OpenAPI's `response_model`, declare an envelope model:

```python
from typing import Generic
from pydantic import BaseModel, Field
from fastapi_extra.types import T

class Envelope(BaseModel, Generic[T]):
    code: str    = Field(default="00000", title="Result code")
    message: str = Field(default="OK", title="Result message")
    data: T | None = Field(default=None, title="Response data")

# Usage in routes:
@app.get("/ping", response_model=Envelope[str])
async def ping() -> Envelope[str]:
    return Envelope(data="pong")
```

The JSON returned by your `APIError` handler is structurally identical to `Envelope`, so you can either keep the current handler or also switch to `Envelope(...)` serialization.

---

## 7. Project-level conventions

1. **Every route must return `APIResult[T]` or `Envelope[T]`** — forbid raw `dict` / `str` returns.
2. **Use namespaced prefixes for custom business codes** (e.g. `ORDER-*`, `PAY-*`, `AUTH-*`) so they never collide with future entries added to `ResultEnum`.
3. **Logging**: In your `APIError` handler, log B- and C- class errors with `logger.exception` (full stacktrace), and A-class errors with `logger.warning` only to reduce noise.
4. **i18n**: For multi-locale deployments, translate `message` in the handler using the current locale. Keep `code` stable across locales.
