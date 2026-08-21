# 统一响应与错误码

为了让前后端契约稳定一致，`fastapi_extra` 提供了一整套统一响应方案：

- **`ResultEnum`**：120+ 条预定义阿里云风格错误码（用户 A / 系统 B / 调用第三方 C 三大类）；
- **`APIResult[T]`**：泛型响应体（`{data: T}`），`APIResult.ok(data, ...)` 一键返回 `APIResponse`；
- **`APIResponse`**：继承 FastAPI `JSONResponse`，使用 Pydantic v2 原生序列化器，`by_alias=True`、保留默认值；
- **`APIError`**：带 `code` + `message` 的可抛异常，用于在业务层中断并返回约定格式。

---

## 1. 响应结构

所有成功 / 失败的接口响应统一为：

```json
{
  "code":    "00000",
  "message": "OK",
  "data":    ... /* 泛型 T */
}
```

其中：

| 字段 | 含义 | 说明 |
|------|------|------|
| `code` | 结果码 | `"00000"` 表示成功；其他按 `ResultEnum` 枚举约定；自定义错误也可直接给字符串。 |
| `message` | 结果说明 | 成功默认为 `"OK"`；失败给出业务可读原因。 |
| `data` | 返回数据 | 泛型 `T`。为了 OpenAPI schema 的完整性，请在路由返回类型中使用 `APIResult[T]`。 |

> 说明：`APIResult` 的 Pydantic 模型本身**只声明** `data` 字段。`code` / `message` 是通过 `APIError` 异常处理器或 `APIResult.ok()` 返回的自定义 JSON。如果希望在 schema 中完整暴露 `code / message / data`，可以自定义一个 `Envelope` 响应模型（参见本文第 6 节）。

---

## 2. `APIResult[T]`：成功返回

### 2.1 基本用法

```python
from fastapi import FastAPI
from fastapi_extra.response import APIResult

app = FastAPI()

@app.get("/ping", response_model=APIResult[str])
async def ping() -> APIResult[str]:
    return APIResult.ok("pong")
```

HTTP 返回：

```json
{"data":"pong"}
```

（若配合全局异常处理器把 `code / message` 也补齐，则返回 `{"code":"00000","message":"OK","data":"pong"}`，见第 5 节。）

### 2.2 自定义状态码 / 响应头

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

## 3. `ResultEnum`：错误码大全

枚举的每个成员都保存 `(code, message)` 二元组：

| 前缀 | 范围 | 示例 |
|------|------|------|
| A | 用户端错误 | `A0400` = "用户请求参数错误"；`A0111` = "用户名已存在"；`A0301` = "访问未授权" |
| B | 系统端错误 | `B0001` = "系统执行出错"；`B0100` = "系统执行超时"；`B0210` = "系统限流" |
| C | 调用第三方出错 | `C0001` = "调用第三方服务出错"；`C0300` = "数据库服务出错"；`C0341` = "主键冲突" |
| 00000 / 99999 | 成功 / 兜底异常 | `SUCCESS = ("00000","OK")`；`FAILED = ("99999","系统异常")` |

典型用法：

```python
from fastapi_extra.response import ResultEnum

result = ResultEnum.A0301          # 访问未授权
code, msg = result.value           # => ("A0301", "访问未授权")
```

> 参考：枚举覆盖了阿里云《API 网关错误码规范》常见条目（用户、登录、权限、参数、资源、上传、版本、隐私、设备、系统、容灾、中间件、数据库、通知等大类）。未覆盖的业务错误请用 `APIError(code=..., message=...)` 自定义字符串。

---

## 4. `APIError`：业务异常

```python
from fastapi_extra.response import APIError, ResultEnum

# 方式一：用 ResultEnum + 可选自定义 message
raise APIError(ResultEnum.A0400, message="username 字段长度必须在 2-32 之间")

# 方式二：直接传 code / message
raise APIError(code="ORDER-001", message="库存不足，下单失败")
```

`APIError` 本身是 `Exception` 的子类，具有：

| 属性 / 方法 | 说明 |
|-------------|------|
| `.code: str` | 错误码（来自 ResultEnum 或自定义） |
| `.message: str` | 错误信息 |
| `str(err)` | 返回 `message` |
| `repr(err)` | 返回 `[CODE]message`，便于日志排查 |

---

## 5. 全局异常处理器（推荐）

把异常统一转为 `{code, message, data}` 的约定格式：

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

这样调用方无论收到**业务错误**还是**参数校验错误**，都能以同样的结构解析，减少前端 `try / except` 分支。

---

## 6. 可选：完整的 Envelope Schema

为了让 OpenAPI 的 `response_model` 完整暴露 `code / message / data` 三个字段，可声明一个包络模型：

```python
from typing import Generic
from pydantic import BaseModel, Field
from fastapi_extra.types import T

class Envelope(BaseModel, Generic[T]):
    code: str    = Field(default="00000", title="结果码")
    message: str = Field(default="OK", title="结果说明")
    data: T | None = Field(default=None, title="返回数据")

# 路由中使用：
@app.get("/ping", response_model=Envelope[str])
async def ping() -> Envelope[str]:
    return Envelope(data="pong")
```

此时你需要把 `APIError` 处理器也改为返回 `Envelope` 对应 JSON（两者已经结构一致）。

---

## 7. 项目级规范建议

1. **路由统一返回 `APIResult[T]` / `Envelope[T]`**，禁止裸 `dict`、`str` 返回；
2. **自定义业务错误码建议使用命名空间前缀**，例如 `ORDER-*` / `PAY-*` / `AUTH-*`，避免后续和 `ResultEnum` 冲突；
3. **日志**：在 `APIError` 处理器里，对 `B-` 类 / `C-` 类错误使用 `logger.exception` 打印堆栈，`A-` 类错误仅 `logger.warning`，以减少噪音；
4. **国际化**：若需要多语言，可在 handler 中查字典把 `message` 替换为当前 locale；保持 `code` 稳定不变。
