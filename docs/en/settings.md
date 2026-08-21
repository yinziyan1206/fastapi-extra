# Settings / Configuration

`fastapi_extra` uses `pydantic-settings` to implement a **multi-layered settings loader**:

```
TOML files  >  Environment variables  >  Init kwargs  >  File secrets
(highest priority)          (lowest priority)
```

The package ships four ready-to-use settings classes:
- **`Settings`**: base app configuration (title / version / debug / mode / root_path …).
- **`DefaultDatabaseSettings`**: adds a `[datasource]` section for the database layer.
- **`DefaultRedisSettings`**: adds a `[redis]` section for the cache layer.
- **`SQLTemplateSettings`**: adds an `[sqlmap]` section for SQL templates.

---

## 1. Configuration files

### 1.1 `config.default.toml` (required)

Resides in your application working directory. Suggested contents:

```toml
# —— Base App settings ——
title   = "My FastAPI Service"
version = "1.0.0"
debug   = false
mode    = "dev"              # dev / test / prod; mode=prod forces debug=False & hides OpenAPI
root_path = ""
include_in_schema = true

# —— Database (consumed by DefaultDatabaseSettings) ——
[datasource]
url = "mysql+asyncmy://root:pass@127.0.0.1:3306/demo?charset=utf8mb4"
echo      = false
echo_pool = false
isolation_level = "READ COMMITTED"
options.pool_size    = 20
options.max_overflow = 40

# —— Redis (consumed by DefaultRedisSettings) ——
[redis]
url = "redis://localhost:6379/0"
max_connections = 50
connection_kwargs.socket_timeout = 5

# —— SQL templates (consumed by SQLTemplateSettings) ——
[sqlmap]
path   = "./template/sql"
suffix = ".sql"
```

### 1.2 `config.custom.toml` (optional)

For per-environment overrides. Write only the fields that need to change, e.g. for production:

```toml
mode  = "prod"
debug = false

[datasource]
url = "mysql+asyncmy://prod_user:***@10.0.0.3:3306/prod_db?charset=utf8mb4"

[redis]
url = "redis://:ProdPass@10.0.0.4:6379/3"
```

The loading order (see §4) guarantees that `config.custom.toml` values override `config.default.toml` values.

### 1.3 Environment variables (higher priority than TOML)

`pydantic-settings` natively reads environment variables. For nested keys use the **double-underscore** separator:

```bash
# equivalent to TOML: mode = "prod"
export MODE=prod

# equivalent to TOML: [datasource] url = "..."
export DATASOURCE__URL="mysql+asyncmy://prod_user:***@..."

# equivalent to TOML: [redis] max_connections = 100
export REDIS__MAX_CONNECTIONS=100
```

> Rule of thumb: a TOML section header `[foo.bar]` maps to env prefix `FOO__BAR__` (two underscores between every level).

---

## 2. `Settings` built-in fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | `str` | `"FastAPI"` | Passed to `FastAPI(title=…)`. Shown in OpenAPI UI. |
| `version` | `str` | `"0.1.0"` | Passed to `FastAPI(version=…)`. |
| `debug` | `bool` | `False` | FastAPI debug flag. |
| `root_path` | `str` | `""` | Set when mounted behind a reverse proxy / API gateway subpath (e.g. `"/v1"`). |
| `include_in_schema` | `bool` | `True` | Whether to generate the OpenAPI schema. |
| `mode` | `"dev" \| "test" \| "prod"` | `"dev"` | Runtime environment. **`mode = prod` forces `include_in_schema=False` AND `debug=False`** — enforced via `validate_mode` post-validator. |

Usage:

```python
from fastapi_extra.settings import Settings

settings = Settings()               # loads TOML + env vars on construction
app = FastAPI(
    title=settings.title,
    version=settings.version,
    debug=settings.debug,
    root_path=settings.root_path,
    docs_url="/docs" if settings.include_in_schema else None,
)
```

---

## 3. Extend with custom sections

Nearly every project needs its own configuration keys (JWT, SMTP, OSS, …). Simply subclass `Settings` and add attributes.

### 3.1 Example: JWT + SMTP

```python
from pydantic import BaseModel, Field
from fastapi_extra.settings import Settings

class JWTConfig(BaseModel):
    secret:      str = Field(default="change-me")
    algorithm:   str = "HS256"
    expire_min:  int = 60 * 24          # 1 day

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

Corresponding TOML:

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

Usage:

```python
settings = AppSettings()
print(settings.jwt.secret)
print(settings.smtp.host)
```

### 3.2 Combine with existing sections

Classes like `DefaultDatabaseSettings` are exactly this pattern. You can inherit them in one shot:

```python
from fastapi_extra.database.session import DefaultDatabaseSettings
from fastapi_extra.cache.redis import DefaultRedisSettings

class FullSettings(DefaultDatabaseSettings, DefaultRedisSettings):
    class JWTConfig(BaseModel):
        secret: str = "change-me"

    jwt: JWTConfig
```

> Note: module-level defaults like `_settings = DefaultDatabaseSettings()` are instantiated at import-time using the global `datasource` / `redis` TOML sections. When you use your own subclass and call `SessionFactory.setup(**overrides)`, you can still pass any derived values in explicitly.

---

## 4. Loading order internals (`settings_customise_sources`)

`Settings.settings_customise_sources` returns sources sorted by **decreasing priority** (first wins):

```python
(
    TomlConfigSettingsSource(settings_cls),   # 1) TOML: config.default.toml + config.custom.toml
    env_settings,                             # 2) Environment variables
    init_settings,                            # 3) kwargs passed to the constructor
    file_secret_settings,                     # 4) File-based secrets (Docker / K8s)
)
```

> Note: `TomlConfigSettingsSource` loads `toml_file=["config.default.toml","config.custom.toml"]`; later entries override earlier ones for the same key.

To change TOML file paths override `model_config`:

```python
class MySettings(Settings):
    model_config = SettingsConfigDict(
        toml_file=["my/defaults.toml", "my/override.toml"],
        validate_default=False,
        extra="ignore",
    )
```

---

## 5. Handling secrets safely

1. **Never commit real passwords in `config.default.toml`**. Use placeholders and apply any of the following in production:
   - Environment variables (most common).
   - `config.custom.toml` (add it to `.gitignore`).
   - Docker Secrets / K8s Secrets via `file_secret_settings`.
2. **Redact before printing**: Pydantic v2 `model_dump()` does not auto-redact. Mark sensitive fields with `Field(json_schema_extra={"sensitive": True})`, or provide a custom `model_serializer`.
3. **`mode="prod"` automatically disables `/docs`** and `debug`, preventing schema / stacktrace leakage in production.

---

## 6. FAQ

### Q1: Why are my environment variables not applied?
- Check naming: `DATASOURCE__URL` (double underscore between levels).
- Make sure the variable is truly exported in the shell / systemd unit / docker-compose.yml that starts the process.
- Inspect values with `Settings().model_dump()` to diagnose.

### Q2: I forgot to set `mode=prod` in production, is there a failsafe?
Yes. Simply `export MODE=prod` and restart. The `validate_mode` validator will enforce `include_in_schema=False` and `debug=False` automatically.

### Q3: Does each request re-read TOML from disk?
No. `pydantic-settings` reads sources once per instantiation. Best practice: **instantiate once at module level and reuse** — this avoids repeated disk I/O.
