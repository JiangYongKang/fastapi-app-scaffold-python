# FastAPI 应用脚手架

在原模板（`FastAPI()` + `/` Hello World）基础上扩展的可直接复用的应用脚手架，提供：

- **分层配置**：代码默认值 → `configs/default.toml` → `configs/<env>.toml` → 显式配置文件 → `APP_*` 环境变量，优先级确定，启动期完成类型转换与校验；
- **共享资源生命周期**：启动时一次性初始化、并发下不重复初始化；未就绪 / 已释放的请求被拒绝且错误原因可区分；关闭流程幂等；
- **按模块登记路由**：统一挂载前缀，重复路径 / 前缀冲突在启动阶段直接报错；
- **统一错误响应信封**：底层异常不会原样透出。

模板原有的开箱即用行为保持不变：不设置任何环境变量、不写任何文件，直接启动即可访问 `GET /` 得到 `{"Hello": "World"}`。

## 目录结构

```
app/
├── config/
│   ├── errors.py          # 可区分原因的配置异常（缺失/类型/取值/未知键/废弃）
│   ├── schema.py          # 配置项声明、校验器、废弃键迁移表
│   └── loader.py          # 分层合并、类型转换、生效值日志
├── core/
│   ├── errors.py          # 应用错误基类（资源未就绪/已释放、路由冲突等）
│   ├── resources.py       # ResourceRegistry：单次初始化 + 幂等关闭
│   ├── router_registry.py # RouterRegistry：模块登记 + 冲突检测
│   └── error_handlers.py  # 统一错误信封
├── modules/
│   ├── root.py            # 根模块：保留 "/"，另含 "/healthz"
│   └── counter/           # 演示模块：共享资源 + /api/counter
└── factory.py             # create_app()：组装配置、资源、路由、lifespan
configs/
├── default.toml           # 所有环境共享的基础层
├── dev.toml / test.toml / prod.toml
main.py                    # 开发入口：python main.py / uvicorn main:app
tests/                     # pytest 测试
```

## 一、配置

### 1. 优先级（后者覆盖前者）

| 层级 | 来源 | 如何指定 |
| --- | --- | --- |
| 1（最低） | 代码默认值 | `app/config/schema.py` 中每个 `FieldSpec` 的 `default` |
| 2 | `configs/default.toml` | 仓库自带 |
| 3 | `configs/<env>.toml` | `APP_ENV` 选择（`dev` / `test` / `prod`，默认 `dev`） |
| 4 | 显式配置文件 | 环境变量 `APP_CONFIG_FILE=/path/to/xxx.toml` |
| 5（最高） | 环境变量 | `APP_` 前缀 |

环境变量与点分键的映射规则：点分键 `server.log_level` 对应环境变量
`APP_SERVER__LOG_LEVEL`（分段用双下划线 `__`，全大写）。布尔值接受
`1/true/yes/on` 与 `0/false/no/off`（大小写不敏感）。

保留变量：`APP_ENV`（选择环境）与 `APP_CONFIG_FILE`（显式配置文件）不会被当作配置项。

当前内置配置项：

| 键 | 类型 | 默认值 | 约束 |
| --- | --- | --- | --- |
| `service.name` | str | `fastapi-app-scaffold` | |
| `service.env` | str | `dev` | `dev` / `test` / `prod`（由 `APP_ENV` 决定） |
| `service.debug` | bool | `false` | |
| `server.host` | str | `127.0.0.1` | |
| `server.port` | int | `8000` | 1–65535 |
| `server.log_level` | str | `info` | `critical/error/warning/info/debug/trace` |
| `counter.initial` | int | `0` | |

### 2. 启动期失败，且原因可区分

类型转换或校验不通过会在 **`create_app()` 阶段直接抛异常**（应用无法启动），
异常类（及 `reason` 字段）区分五类原因：

| 异常类 | `reason` | 触发场景 |
| --- | --- | --- |
| `MissingConfigError` | `missing` | 必填字段在所有层都没有值 |
| `ConfigTypeError` | `type` | 值无法转成声明类型（如端口填了 `abc`） |
| `ConfigValidationError` | `value` | 类型正确但取值非法（端口 70000、枚举不匹配等） |
| `UnknownConfigKeyError` | `unknown_key` | 出现 schema 中未声明的键（拼写错误等） |
| `DeprecatedConfigError` | `deprecated` | 使用了已废弃的旧配置项 |

每个异常都带 `key` 属性指明具体是哪个配置项。

### 3. 废弃项兼容规则

废弃项 **不会被静默忽略**，而是启动失败并给出迁移提示。废弃清单维护在
`app/config/schema.py` 的 `DEPRECATED_KEYS`：

| 废弃键 | 替代方案 |
| --- | --- |
| `debug` | `service.debug`（`APP_SERVICE__DEBUG`） |
| `log_level` | `server.log_level`（`APP_SERVER__LOG_LEVEL`） |
| `server.bind` | `server.host` |
| `counter.start` | `counter.initial` |

新增废弃项时，只需往 `DEPRECATED_KEYS` 加一行 `"旧键": "迁移说明"`。
新增配置项时在 `build_schema()` 中增加 `FieldSpec`，即可自动获得类型转换、
校验、环境变量映射与未知键拦截。

### 4. 生效配置与判定依据日志

启动时 `app.config` logger 以 INFO 级别打印：合并顺序、实际应用了哪些层、
每个键的最终值以及它来自哪一层，例如：

```
INFO app.config: effective config server.port = 8443  [environment]
INFO app.config: effective config server.host = '0.0.0.0'  [file:.../configs/prod.toml]
INFO app.config: effective config counter.initial = 0  [code-default]
```

### 5. 编程式加载

```python
from app.config.loader import load_config, load_config_with_sources

cfg = load_config(env="prod", environ={"APP_SERVER__PORT": "9000"})
loaded = load_config_with_sources()  # 额外返回 .sources（逐键来源）与 .env
```

## 二、共享资源生命周期

资源是实现 `open()` / `close()` 两个方法的对象（见 `core/resources.py` 的
`Resource` Protocol），例如 `app/modules/counter/resources.py` 中的计数器。

约定与保证：

1. **注册发生在启动前**：在 `factory.build_resource_registry()` 中
   `registry.register("名字", 资源实例)`；重名注册直接报错。
2. **启动时初始化一次**：FastAPI lifespan 启动阶段调用
   `resources.initialize()`，按注册顺序依次 `open()`。
3. **并发不会初始化两次**：多个线程同时进入 `initialize()` 时，只有一个
   leader 真正执行 `open()`，其余阻塞等待初始化完成。
4. **请求侧获取资源**：路由内通过 `request.app.state.resources.acquire("名字")`
   获取。到达时机不同，错误可区分：
   - 尚未启动完成 → `503 resource_not_ready`（`details.state` 为 `new` / `failed`）；
   - 已关闭后到达 → `503 resource_released`（`details.state` 为 `released`）。
   - 若希望请求等待启动完成，可用 `acquire(name, wait=True)`。
5. **关闭幂等**：`shutdown()` 可重复调用、未启动也可调用，均不报错；
   已就绪资源按注册逆序 `close()`，单个资源关闭异常只记录日志、不影响其余资源。

## 三、路由登记

模块各自创建 `APIRouter`，在 `factory.build_router_registry()` 中统一登记：

```python
registry.register(root_router, prefix="", name="root")
registry.register(counter_router, prefix="/api", name="counter")
```

以下冲突在 **`routers.mount(app)`（启动阶段）** 抛 `RouteConflictError`，
不会出现后登记悄悄覆盖先登记的情况：

- 两个模块使用相同的非空前缀；
- 同位置静态段与参数段冲突（`/users/me` vs `/users/{id}`），前缀级和路由级都会检测；
- 相同 HTTP 方法 + 相同完整路径被登记两次。

多个模块可以同时挂根前缀 `""`，此时仍按完整方法+路径去重。

## 四、统一错误响应

所有错误（应用错误、参数校验 422、404/405、路由冲突、未捕获异常）都返回同一结构：

```json
{"error": {"code": "resource_not_ready",
           "message": "resource 'counter' is not ready yet",
           "details": {"resource": "counter", "state": "new"}}}
```

未捕获异常返回 `500 internal_error`，异常详情只进服务器日志、不回传客户端
（`service.debug=true` 时响应中也仅附带异常类名，不含堆栈和内部信息）。

## 五、本地验证

```bash
# 安装依赖（需要 uv）
uv sync

# 启动开发服务器（默认 APP_ENV=dev）
uv run uvicorn main:app --reload
# 或
uv run python main.py

# 运行全部测试
uv run pytest

# 切换环境 / 用环境变量覆盖单个配置
APP_ENV=prod APP_SERVER__PORT=8443 uv run uvicorn main:app

# 使用仓库外的自定义配置文件
APP_CONFIG_FILE=/etc/myapp/local.toml uv run uvicorn main:app

# 观察启动日志中实际生效的配置及判定依据
uv run python -c "from app.factory import create_app; create_app()"
```

测试覆盖范围（`tests/`）：

- `test_config.py`：默认值、层级优先级、逐键来源日志，以及
  缺失 / 类型错误 / 非法取值 / 未知键 / 废弃键五类失败的区分；
- `test_resources.py`：未就绪拒绝、并发初始化仅一次、失败资源、
  关闭幂等、关闭后拒绝（`resource_released`）及 HTTP 层信封；
- `test_routing.py`：重复前缀 / 重复路径 / 静态与参数段冲突、
  配置非法导致启动失败、统一错误信封、底层异常不泄露。
