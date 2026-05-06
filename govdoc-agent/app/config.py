import json  # JSON 解析库，用于读取 config/model.json
import os  # 操作系统库，用于读取环境变量
from pathlib import Path  # 路径操作库，用于处理文件路径

# 获取项目根目录（govdoc-agent/）的绝对路径
# __file__ 是当前文件 config.py 的路径
# .resolve() 将相对路径转换为绝对路径
# .parent.parent 得到 app/ 的父目录，即项目根目录
_ROOT = Path(__file__).resolve().parent.parent

# config/model.json 文件的完整路径
_MODEL_JSON_PATH = _ROOT / "config" / "model.json"


def _load_dotenv() -> None:
    """加载项目根目录下的 .env 文件到环境变量（如果存在）。"""
    try:
        from dotenv import load_dotenv

        env_path = _ROOT / ".env"  # .env 文件路径
        if env_path.is_file():  # 仅当文件存在时加载
            load_dotenv(env_path)
    except ImportError:
        # 如果 python-dotenv 未安装，忽略错误（静默失败）
        pass


def _read_env_file_value(key: str) -> str:
    """从项目根目录 .env 读取单个键值（进程环境缺失时兜底）。"""
    env_path = _ROOT / ".env"
    if not env_path.is_file():
        return ""
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            k, v = raw.split("=", 1)
            if k.strip() != key:
                continue
            return v.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def _load_model_json() -> dict:
    """读取 config/model.json 中的 llm 段；文件缺失或解析失败时返回空 dict。"""
    if not _MODEL_JSON_PATH.is_file():  # 文件不存在时返回空字典
        return {}
    try:
        with open(_MODEL_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)  # 解析 JSON 文件
        llm = data.get("llm")  # 获取 llm 配置段
        # 确保 llm 是字典类型，否则返回空字典
        return llm if isinstance(llm, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        # 文件读取错误、JSON 解析错误或类型错误时返回空字典
        return {}


# 执行顺序：先加载 .env，再读取 model.json，最后创建 Settings 实例
_load_dotenv()  # 加载 .env 文件到环境变量
_MODEL_LLM = _load_model_json()  # 读取 model.json 中的 llm 配置段


def _llm_str(key: str) -> str:
    """仅从 model.json 的 llm 段读取字符串；缺省或空则返回 ""。"""
    raw = _MODEL_LLM.get(key)  # 从 llm 配置中获取指定键的值
    if raw is None:  # 键不存在时返回空字符串
        return ""
    return str(raw).strip()  # 转换为字符串并去除首尾空白


def _llm_float(key: str, if_missing: float) -> float:
    """
    仅从 model.json 读取浮点数；
    键不存在或为空串时使用 if_missing（作为业务默认值）。
    """
    raw = _MODEL_LLM.get(key)
    if raw is None:  # 键不存在
        return if_missing
    if isinstance(raw, str) and raw.strip() == "":  # 值为空字符串
        return if_missing
    return float(raw)  # 转换为浮点数


def _llm_int(key: str, if_missing: int) -> int:
    """仅从 model.json 读取整数；键不存在或为空串时使用 if_missing。"""
    raw = _MODEL_LLM.get(key)
    if raw is None:  # 键不存在
        return if_missing
    if isinstance(raw, str) and raw.strip() == "":  # 值为空字符串
        return if_missing
    return int(raw)  # 转换为整数


def _llm_bool(key: str, if_missing: bool) -> bool:
    """仅从 model.json 读取布尔值；支持 bool/None/空串 类型。"""
    raw = _MODEL_LLM.get(key)
    if isinstance(raw, bool):  # 已经是布尔类型，直接返回
        return raw
    if raw is None:  # 键不存在
        return if_missing
    if isinstance(raw, str) and raw.strip() == "":  # 值为空字符串
        return if_missing
    # 将字符串转换为布尔值（仅 "true"（不区分大小写）返回 True）
    return str(raw).lower() == "true"


def _parse_available_models() -> list[dict[str, str]]:
    """
    解析 llm.available_models 配置项。
    每项包含：
    - id：模型的唯一标识符（用于 API 调用）
    - label：模型的显示名称（用于前端展示）
    """
    raw = _MODEL_LLM.get("available_models")
    if not isinstance(raw, list):  # 不是列表类型时返回空列表
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):  # 跳过非字典项
            continue
        # 获取模型 ID，依次尝试 id、modelName 字段
        mid = str(item.get("id") or item.get("modelName") or "").strip()
        if not mid:  # 跳过空 ID
            continue
        # 获取显示名称，依次尝试 label、modelDisplayName 字段，默认为 ID
        label = str(item.get("label") or item.get("modelDisplayName") or mid).strip()
        out.append({"id": mid, "label": label})
    return out


class Settings:
    """
    应用配置类，所有配置项在此定义。
    配置来源优先级：
    1. LLM 相关项：仅来自 config/model.json（不使用环境变量）
    2. 其他项：从环境变量读取，不存在则使用默认值
    """

    # 应用名称
    app_name = "govdoc-agent"

    # 数据库连接 URL，默认使用相对路径的 SQLite 数据库
    # 格式：sqlite:///数据库文件路径（相对于项目根目录）
    database_url = os.getenv("NEW_APP_DATABASE_URL", "mysql+pymysql://root:Rzvgz180$+@localhost:3306/govdoc_agent")

    # 旧系统鉴权服务的基础 URL（用于 Cookie 鉴权时回调验证）
    # 读取环境变量，不存在则为空字符串；末尾斜杠会被去除
    legacy_auth_base_url = os.getenv("LEGACY_AUTH_BASE_URL", "").rstrip("/")

    # 旧系统业务服务的基础 URL（用于调用旧系统 API）
    # 读取环境变量，不存在则为空字符串；末尾斜杠会被去除
    legacy_service_base_url = os.getenv("LEGACY_SERVICE_BASE_URL", "").rstrip("/")
    # 旧系统固定 Cookie（可选）。当请求未携带 Cookie 时，用于本地联调兜底。
    # 示例：SESSION=xxx; token=xxx; sso_token=xxx
    # 兼容历史变量名 DEBUG_FORCE_LEGACY_COOKIE，优先使用 LEGACY_FIXED_COOKIE。
    legacy_fixed_cookie = (
        os.getenv("LEGACY_FIXED_COOKIE")
        or _read_env_file_value("LEGACY_FIXED_COOKIE")
        or os.getenv("DEBUG_FORCE_LEGACY_COOKIE")
        or _read_env_file_value("DEBUG_FORCE_LEGACY_COOKIE")
        or ""
    ).strip()

    # 旧系统 HTTPS 证书校验策略：
    # - 默认 false：兼容内网自签名证书（避免 SSL CERTIFICATE_VERIFY_FAILED）
    # - 生产建议设为 true，或配置 legacy_ca_bundle 指向 CA 证书文件
    legacy_tls_verify = os.getenv("LEGACY_TLS_VERIFY", "false").lower() == "true"
    legacy_ca_bundle = os.getenv("LEGACY_CA_BUNDLE", "").strip()

    # 旧系统的根路径（用于前端路由跳转）
    legacy_system_url = os.getenv("LEGACY_SYSTEM_URL", "/areport")

    # 是否启用开发模式下的 Mock 鉴权（用于本地开发，跳过真实鉴权）
    # 默认为 true，生产环境应设为 false
    enable_dev_auth_mock = os.getenv("ENABLE_DEV_AUTH_MOCK", "true").lower() == "true"

    # 以下 LLM 相关项**仅**来自 config/model.json 的 llm 段，不使用环境变量
    # 这样设计是为了将 LLM 配置集中在 model.json 中管理

    # LLM 服务的基础 API 地址（支持 OpenAI 兼容接口）
    # 读取后去除末尾斜杠，确保 URL 格式一致
    llm_base_url = _llm_str("base_url").rstrip("/")

    # 完整的 chat/completions 接口 URL（优先级高于 base_url）
    # 当 base_url 路径与网关实际路径不一致时，直接填写完整地址可避免 404
    llm_chat_completions_url = _llm_str("chat_completions_url").strip()

    # LLM 服务的 API 密钥
    llm_api_key = _llm_str("api_key")

    # 默认使用的模型标识符（用于 API 调用）
    llm_default_model = _llm_str("default_model")

    # LLM 调用的超时时间（单位：秒），默认 90 秒
    llm_timeout_seconds = _llm_float("timeout_seconds", 90.0)

    # 是否启用 Planner 功能（Planner 负责生成执行计划，调度 sub-agent）
    # 默认启用
    enable_model_planner = _llm_bool("enable_planner", True)

    # 用于 Planner 的模型（若为空，默认使用 default_model）
    planner_model = _llm_str("planner_model")

    # Planner 模型的温度参数（影响输出随机性），默认 0.1
    planner_temperature = _llm_float("planner_temperature", 0.1)

    # Planner 生成的最大执行步骤数（防止步骤过多导致执行时间过长），默认 5
    planner_max_steps = _llm_int("planner_max_steps", 5)

    # 可用模型列表（用于前端下拉选择）
    llm_available_models = _parse_available_models()

    # 是否开启运行时详细日志（用于调试 Agent 执行过程）
    debug_runtime_logs = os.getenv("NEW_APP_DEBUG_RUNTIME_LOGS", "true").lower() == "true"

    # 是否在持久化 SSE 事件前做瘦身（只保留前端渲染所需字段，剔除 taskPacket/registry/raw 等重字段）
    # 完整数据仍保留在 V4ConversationRun.input_payload_json 与 V4ConversationMessage.meta_json，便于回放与调试
    # 可通过环境变量关闭以便排障
    slim_event_payload = os.getenv("NEW_APP_SLIM_EVENT_PAYLOAD", "true").lower() == "true"

    # 是否在失败事件中携带 traceback（仅 debug 场景使用）
    include_error_traceback = os.getenv("NEW_APP_INCLUDE_ERROR_TRACEBACK", "false").lower() == "true"

    # 运行时日志的最大字符数（单条日志超过此长度会被截断）
    debug_log_max_chars = int(os.getenv("NEW_APP_DEBUG_LOG_MAX_CHARS", "40000"))

    # 运行时日志中字符串字段的最大字符数
    debug_log_max_string_chars = int(
        os.getenv("NEW_APP_DEBUG_LOG_MAX_STRING_CHARS", "12000")
    )

    # 工作区根目录（用户文档的存储位置）
    # 默认 /data/new-app/users（容器内路径）
    workspace_root = os.getenv("NEW_APP_WORKSPACE_ROOT", "/data/new-app/users")

    # 上下文压缩时保留的最近消息数（最近的 N 条消息不会被压缩）
    compaction_preserve_recent_messages = int(
        os.getenv("NEW_APP_COMPACTION_PRESERVE_RECENT_MESSAGES", "4")
    )

    # 上下文压缩后的最大字符数
    compaction_max_chars = int(os.getenv("NEW_APP_COMPACTION_MAX_CHARS", "8000"))

    # 摘要的最大字符数
    compaction_summary_max_chars = int(
        os.getenv("NEW_APP_COMPACTION_SUMMARY_MAX_CHARS", "1200")
    )

    # 摘要的最大行数
    compaction_summary_max_lines = int(
        os.getenv("NEW_APP_COMPACTION_SUMMARY_MAX_LINES", "24")
    )

    # 摘要中单行的最大字符数（超过此长度的行会被截断）
    compaction_summary_max_line_chars = int(
        os.getenv("NEW_APP_COMPACTION_SUMMARY_MAX_LINE_CHARS", "160")
    )

    # CORS 允许的跨域来源列表（支持多个，用逗号分隔）
    # 默认允许本地开发常用端口：4173（Vite 生产预览）、5173（Vite 开发）、3000（Next.js）
    cors_origins = [
        item.strip()  # 去除每项的首尾空白
        for item in os.getenv(
            "NEW_APP_CORS_ORIGINS",
            # 默认值：本地开发常用端口
            "http://127.0.0.1:4173,http://localhost:4173,http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000",
        ).split(",")  # 按逗号分割为列表
        if item.strip()  # 过滤掉空字符串
    ]


# 创建 Settings 单例实例，供其他模块导入使用
settings = Settings()
