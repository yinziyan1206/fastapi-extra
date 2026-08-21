# 配置管理（Settings）

`fastapi_extra` 基于 `pydantic-settings` 提供一套**多层级加载**的配置体系：

```
TOML 配置文件  >  环境变量  >  初始化参数  >  文件密钥
（优先级从高到低）
```

并预置了：
- **`Settings`**：基础 App 配置（title / version / debug / mode / root_path 等）；
- **`DefaultDatabaseSettings`**：带 `[datasource]` 段的数据库配置；
- **`DefaultRedisSettings`**：带 `[redis]` 段的 Redis 配置；
- **`SQLTemplateSettings`**：带 `[sqlmap]` 段的 SQL 模板配置。

---

## 1. 配置文件

### 1.1 `config.default.toml`（必选）

默认放在项目**工作目录**下。推荐内容：

```toml
# —— 基础 App 配置 ——
title   = "My FastAPI Service"
version = "1.0.0"
debug   = false
mode    = "dev"              # dev / test / prod；mode = prod 时强制关闭 debug & OpenAPI schema
root_path = ""
include_in_schema = true

# —— 数据库（DefaultDatabaseSettings 会读取 datasource 段）——
[datasource]
url = "mysql+asyncmy://root:pass@127.0.0.1:3306/demo?charset=utf8mb4"
echo      = false
echo_pool = false
isolation_level = "READ COMMITTED"
options.pool_size    = 20
options.max_overflow = 40

# —— Redis（DefaultRedisSettings 会读取 redis 段）——
[redis]
url = "redis://localhost:6379/0"
max_connections = 50
connection_kwargs.socket_timeout = 5

# —— SQL 模板（SQLTemplateSettings 会读取 sqlmap 段）——
[sqlmap]
path   = "./template/sql"
suffix = ".sql"
```

### 1.2 `config.custom.toml`（可选）

用于部署环境覆盖默认值。例如生产环境可以只写需要覆盖的字段：

```toml
mode  = "prod"
debug = false

[datasource]
url = "mysql+asyncmy://prod_user:***@10.0.0.3:3306/prod_db?charset=utf8mb4"

[redis]
url = "redis://:ProdPass@10.0.0.4:6379/3"
```

加载顺序由 `Settings.settings_customise_sources` 显式指定（见第 4 节），**`config.custom.toml` 会覆盖 `config.default.toml`**。

### 1.3 环境变量（比 TOML 优先级更高）

`pydantic-settings` 原生支持从环境变量加载。对嵌套字段，使用**双下划线**分隔：

```bash
# 等价于 TOML 的 mode = "prod"
export MODE=prod

# 等价于 [datasource] url = "..."
export DATASOURCE__URL="mysql+asyncmy://prod_user:***@..."

# 等价于 [redis] max_connections = 100
export REDIS__MAX_CONNECTIONS=100
```

> 注意：TOML 的 `[section.key]` 对应环境变量是 `SECTION__KEY`（两个下划线）。

---

## 2. `Settings` 内置字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `title` | `str` | `"FastAPI"` | 传给 `FastAPI(title=...)`，显示在 OpenAPI 页面。 |
| `version` | `str` | `"0.1.0"` | 传给 `FastAPI(version=...)`。 |
| `debug` | `bool` | `False` | 是否开启 debug 模式。 |
| `root_path` | `str` | `""` | 部署在反向代理 / API 网关子路径时，设置为 `"/v1"` 等。 |
| `include_in_schema` | `bool` | `True` | 是否生成 OpenAPI schema。 |
| `mode` | `"dev" \| "test" \| "prod"` | `"dev"` | 运行环境。**`mode = prod` 会自动把 `include_in_schema=False` 且 `debug=False`**（由 `validate_mode` post-validator 强制执行）。 |

示例：

```python
from fastapi_extra.settings import Settings

settings = Settings()  # 自动从 TOML + 环境变量加载
app = FastAPI(
    title=settings.title,
    version=settings.version,
    debug=settings.debug,
    root_path=settings.root_path,
    docs_url="/docs" if settings.include_in_schema else None,
)
```

---

## 3. 扩展自定义配置段

几乎每个项目都需要自定义字段（JWT、邮件、OSS……）。只需继承 `Settings` 追加属性即可。

### 3.1 示例：JWT + SMTP

```python
from pydantic import BaseModel, Field
from fastapi_extra.settings import Settings

class JWTConfig(BaseModel):
    secret:      str = Field(default="change-me")
    algorithm:   str = "HS256"
    expire_min:  int = 60 * 24          # 1 天

class SMTPConfig(BaseModel):
    host:     str
    port:     int = 465
    use_ssl:  bool = True
    username: str
    password: str
    from_:    str = Field(alias="from", default="noreply@example.com")

class AppSettings(Settings):
    jwt:  JWTConfig
    smtp: SMTPConfig
```

对应的 TOML：

```toml
[jwt]
secret     = "please-change-this"
algorithm  = "HS256"
expire_min = 1440

[smtp]
host     = "smtp.example.com"
port     = 465
use_ssl  = true
username = "noreply@example.com"
password = "xxxxxx"
from     = "noreply@example.com"
```

使用：

```python
settings = AppSettings()
print(settings.jwt.secret)
print(settings.smtp.host)
```

### 3.2 与现有段组合

`DefaultDatabaseSettings` 等就是这么做的，你可以一次性继承所有：

```python
from fastapi_extra.database.session import DefaultDatabaseSettings
from fastapi_extra.cache.redis import DefaultRedisSettings

class FullSettings(DefaultDatabaseSettings, DefaultRedisSettings):
    class JWTConfig(BaseModel):
        secret: str = "change-me"

    jwt: JWTConfig
```

> 由于默认 settings（如 `_settings = DefaultDatabaseSettings()`）是模块加载阶段就实例化的，它们读取的是「公共配置类 + 全局 datasource / redis 段」。如果你用自定义子类实例化了 `SessionFactory.setup(**override)`，可以按需要把配置字段重新透传过去。

---

## 4. 加载顺序的实现（`settings_customise_sources`）

`Settings.settings_customise_sources` 返回按**优先级从高到低**的 source 列表：

```python
(
    TomlConfigSettingsSource(settings_cls),   # 1) TOML: config.default.toml + config.custom.toml
    env_settings,                             # 2) 环境变量
    init_settings,                            # 3) 实例化时的 kwargs
    file_secret_settings,                     # 4) 文件密钥（docker secrets 等）
)
```

> 注：`TomlConfigSettingsSource` 本身按 `toml_file=["config.default.toml","config.custom.toml"]` 顺序读取，后者覆盖前者。

如果你要修改 TOML 文件名 / 路径，只需覆盖 `model_config`：

```python
class MySettings(Settings):
    model_config = SettingsConfigDict(
        toml_file=["my/defaults.toml", "my/override.toml"],
        validate_default=False,
        extra="ignore",
    )
```

---

## 5. 敏感信息安全

1. **不要把真实密码提交进 `config.default.toml`**。保留占位符即可，生产用以下任一方式覆盖：
   - 环境变量（最常见）；
   - `config.custom.toml`（加到 `.gitignore`）；
   - Docker Secrets / K8s Secrets（`file_secret_settings`）。
2. **打印配置前脱敏**：Pydantic v2 的 `model_dump` 不会自动脱敏，你可以用 `Field(json_schema_extra={"sensitive": True})` 打标，或自定义 `__str__` / `model_serializer`。
3. **`mode="prod"` 会自动关闭 `/docs` / `debug`**，防止生产环境泄露 schema 与堆栈。

---

## 6. 常见问题

### Q1：为什么我的环境变量没生效？
- 检查命名规则：`DATASOURCE__URL`（双下划线），且变量名匹配**模型字段名**而非 TOML 标题；
- 确认启动进程的 shell / systemd unit / docker-compose.yml 是否真的 `export` 了该变量；
- 用 `Settings().model_dump()` 打印当前值排查。

### Q2：生产环境忘了写 `mode=prod`？
没关系，只要启动时 `export MODE=prod` 即可。`validate_mode` 会自动把 `include_in_schema=False`、`debug=False`。

### Q3：多进程加载是否每次都读磁盘？
`pydantic-settings` 默认会在实例化时读取 TOML。建议：**每个进程只实例化一次**（例如在模块级别实例化并全局复用），避免频繁 IO。
