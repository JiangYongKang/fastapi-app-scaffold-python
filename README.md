# FastAPI 应用脚手架

在最小 FastAPI 模板基础上扩展的可复用脚手架，提供：

- **分层配置合并**：默认值 → 配置文件 → 环境变量，优先级确定，启动期严格校验；
- **共享资源生命周期**：并发安全的单次初始化、就绪/释放状态区分、幂等关闭；
- **按模块登记路由**：统一前缀，重复路径/前缀在启动阶段直接报错；
- **统一错误信封**：所有对外错误结构一致，底层异常不泄露。

脚手架保留了模板的开箱即用行为：直接运行后 `GET /` 仍返回
`{"Hello": "World"}`，无需任何配置即可启动。

---

## 1. 快速开始

```bash
uv sync                 # 安装依赖
python main.py          # 直接运行（127.0.0.1，随机端口）
# 或
uv run uvicorn main:app --reload
```

启动后：

| 路径 | 说明 |
| --- | --- |
| `GET /` | 模板原有的 Hello World |
| `GET /healthz` | 存活探针，不依赖任何资源 |
| `GET /readyz` | 就绪探针，汇总各资源状态 |
| `GET /api/info` | 示例业务接口，演示如何使用共享资源 |

按环境启动：

```bash
APP_ENVIRONMENT=production uv run uvicorn main:app
```

---

## 2. 配置

### 2.1 优先级（从低到高，后者覆盖前者）

1. **内置默认值** —— `app/config/schema.py` 中每个 `FieldSpec` 的 `default`；
2. **配置文件** —— 默认加载 `configs/<环境名>.toml`，环境名由
   `APP_ENVIRONMENT` 决定（默认 `development`，对应 `configs/development.toml`）。
   文件不存在时跳过，不报错；显式指定的文件不存在则直接失败；
3. **环境变量** —— 白名单读取下表声明的变量，**优先级最高**。

> 判定是**逐字段**进行的：某个字段在环境变量里出现就用环境变量，
> 否则看文件，再否则用默认值。空字符串的环境变量视为"未设置"。

启动日志会打印每个字段的**生效值与来源层**，形如：

```
INFO app: 生效配置: app_name='...' environment='development' ...
INFO app:   server.port = 8000 <- file:configs/development.toml
INFO app:   app.name = 'svc' <- env:APP_NAME
```

### 2.2 配置项一览

| 点分层级键（TOML） | 环境变量 | 类型 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `app.name` | `APP_NAME` | str | `fastapi-app-scaffold` | 非空 |
| `app.environment` | `APP_ENVIRONMENT` | str | `development` | 非空 |
| `app.debug` | `APP_DEBUG` | bool | `false` | `true/false/1/0/yes/no/on/off`（大小写不敏感） |
| `app.log_level` | `APP_LOG_LEVEL` | str | `INFO` | `DEBUG/INFO/WARNING/ERROR/CRITICAL`（大小写不敏感） |
| `api.prefix` | `API_PREFIX` | str | `/api` | 必须以 `/` 开头 |
| `server.host` | `SERVER_HOST` | str | `127.0.0.1` | 非空 |
| `server.port` | `SERVER_PORT` | int | `8000` | 1–65535 |

TOML 使用嵌套表表达点分层级：

```toml
[app]
name = "my-service"
debug = true
log_level = "debug"

[api]
prefix = "/api"

[server]
host = "0.0.0.0"
port = 8080
```

### 2.3 启动期失败原因（彼此可区分）

配置问题一律在**启动阶段**抛出 `app.config.errors` 下的具体异常，
应用不会带病运行：

| 异常 | 触发原因 |
| --- | --- |
| `MissingConfigError` | 必填字段在默认值、文件、环境变量三层都缺失 |
| `ConfigTypeError` | 值无法转换为声明类型（如端口写成 `"abc"`、布尔写成 `"maybe"`） |
| `ConfigValidationError` | 类型正确但取值非法（端口越界、枚举不合法、前缀不以 `/` 开头、空字符串） |
| `DeprecatedConfigError` | 使用了已废弃的旧配置项（见 2.4） |
| `UnknownConfigKeyError` | 配置文件出现 schema 未定义的键（多为拼写错误） |

### 2.4 兼容规则：废弃项不静默忽略

脚手架不会悄悄忽略旧配置，而是**直接报错并告知替代项**：

| 废弃写法 | 替代写法 |
| --- | --- |
| 文件根级 `debug` | `app.debug`（写入 `[app]` 表） |
| 文件根级 `name` | `app.name` |
| 文件根级 `log_level` | `app.log_level` |
| 环境变量 `DEBUG` | `APP_DEBUG` |
| 环境变量 `APP_PORT` | `SERVER_PORT` |

新增/废弃字段都集中在 `app/config/schema.py` 的
`FIELDS`、`DEPRECATED_FILE_KEYS`、`DEPRECATED_ENVS` 三处维护。

---

## 3. 共享资源生命周期

资源指数据库连接池、HTTP 客户端、消息队列生产者等"应用级单例"。

### 3.1 约定

1. 继承 `app.resources.base.Resource`，设置唯一 `name`，
   实现 `async startup()` 与 `async shutdown()`；
2. 在 `app/application.py` 的 `build_app()` 中通过
   `resources.register(...)` 登记（**必须在应用启动前**）；
3. 资源由 FastAPI lifespan 统一驱动：应用启动时 `startup_all()`，
   关闭时 `shutdown_all()`。

### 3.2 保证

- **只初始化一次**：每个资源持有独立的 `asyncio.Lock`，
  即使初始化过程中有并发请求/协程同时触发，`startup()` 也只执行一次；
- **状态可区分的拒绝**：
  - 资源尚未就绪（`created`/`starting`）→ `ResourceNotReadyError`
    （HTTP 503，`code=resource_not_ready`）；
  - 资源正在关闭/已释放（`stopping`/`released`）→
    `ResourceReleasedError`（HTTP 503，`code=resource_released`）；
- **幂等关闭**：`shutdown_all()` 重复调用不报错、不重复释放；
  按登记逆序释放，未启动成功的资源也会被安全标记为 `released`；
- **失败可重试**：`startup()` 抛错时资源回到 `created`，
  下一次启动会重新尝试。

### 3.3 在请求中使用

通过依赖注入获取资源，状态检查由依赖统一完成：

```python
from fastapi import APIRouter, Depends
from app.resources.deps import resource_dependency

router = APIRouter()

@router.get("/orders")
async def list_orders(db = Depends(resource_dependency("database"))):
    return await db.fetch_orders()
```

资源未就绪/已释放时无需在业务代码里判空，依赖会抛出资源域异常，
由全局处理器转换为统一结构的 503。

查看当前各资源状态：`GET /readyz`。

---

## 4. 路由组织与登记

业务模块放在 `app/modules/`，每个模块导出三件套：

```python
# app/modules/orders.py
from fastapi import APIRouter

MODULE_NAME = "orders"   # 全局唯一的模块名
PREFIX = "/orders"       # 模块前缀，必须以 / 开头
router = APIRouter()

@router.get("", tags=[MODULE_NAME])
def list_orders(): ...
```

在 `app/application.py` 的 `_build_registry()` 中登记：

```python
registry.register_module(orders.MODULE_NAME, orders.PREFIX, orders.router)
```

所有业务模块统一挂载在 `api.prefix` 下，最终路径为
`api.prefix + 模块前缀 + 路由路径`（默认即 `/api/orders`）。

**冲突在启动阶段直接抛 `RouteConflictError`，后登记的不会覆盖先登记的：**

- 模块名重复；
- 模块前缀重复（`/orders` 与 `/orders/` 视为相同）；
- 任意两个模块出现"HTTP 方法 + 全路径"完全相同的路由
  （`/x` 与 `/x/` 视为冲突；同路径不同方法允许）。

系统路由（`/`、`/healthz`、`/readyz`）不属于业务注册表，
通过 `_register_system_modules()` 直接挂在根路径，不受 `api.prefix` 影响。

---

## 5. 统一错误响应

所有错误（含 404、422、500 以及资源域错误）都返回同一信封：

```json
{
  "error": {
    "code": "resource_not_ready",
    "message": "资源 'database' 尚未就绪（state=created），请在应用启动完成后再试",
    "details": { }
  }
}
```

未捕获异常只返回通用的 `{"code": "internal_error", "message": "服务器内部错误，请稍后重试"}`，
真实堆栈仅写入服务端日志，**不会透出底层异常类型或内部细节**。

---

## 6. 本地验证

```bash
# 全量测试（57 个用例：配置非法 / 资源未就绪 / 路由冲突等）
uv run pytest

# 只跑某一类
uv run pytest tests/test_config.py -v
uv run pytest tests/test_resources.py -v
uv run pytest tests/test_routing.py -v
uv run pytest tests/test_app.py -v

# 类型/语法编译检查
python -m compileall app main.py tests

# 手动验证各环境
APP_ENVIRONMENT=development uv run uvicorn main:app
APP_NAME=svc SERVER_PORT=9000 uv run uvicorn main:app

# 观察启动失败（任选其一，均应在启动阶段报错且原因不同）
APP_PORT=8000 uv run uvicorn main:app            # DeprecatedConfigError
APP_DEBUG=maybe uv run uvicorn main:app          # ConfigTypeError
SERVER_PORT=70000 uv run uvicorn main:app        # ConfigValidationError
```

---

## 7. 目录结构

```
app/
  application.py          # 应用装配（配置→资源→路由→错误处理→lifespan）
  errors.py               # 统一错误信封与全局异常处理器
  config/
    schema.py             # 字段清单、类型、约束、废弃映射
    loader.py             # 分层合并与启动期校验
    errors.py             # 五类可区分的配置错误
  resources/
    base.py               # Resource 抽象基类与状态机
    manager.py            # 单次初始化 / 并发安全 / 幂等关闭
    deps.py               # FastAPI 依赖工厂
    app_info.py           # 示例资源（新项目可照抄）
  routing/
    registry.py           # 模块登记、统一前缀、冲突检测
  modules/
    root.py               # GET /（保留开箱即用）
    health.py             # /healthz、/readyz
    info.py               # 示例业务模块
configs/
  development.toml        # 默认环境配置
  production.example.toml # 生产配置示例
tests/                    # 配置 / 资源 / 路由 / 端到端测试
main.py                   # 入口（ASGI: main:app）
```
