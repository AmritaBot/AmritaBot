/** 与后端 API 对应的类型定义 */

/** 菜单 / 路由注册表 */
export interface MenuRoute {
  path: string; // FastAPI 风格，如 /system/confedit/{owner_name}
  name: string;
  category: string;
  icon: string | null;
  hidden: boolean;
  /** iframe 页面地址（第三方插件用，无需重新构建前端） */
  external_url?: string | null;
  /** 运行期 ESM 模块地址，默认导出 React 组件（第三方插件用） */
  module_url?: string | null;
}

export interface MenuData {
  routes: MenuRoute[];
  /** Amrita 版本号（如 0.1.0），用于侧边栏等展示 */
  version: string;
}

/** 认证 */
export interface AuthMe {
  username: string;
}

/** 仪表盘 */
export interface DashboardData {
  bot_connected: boolean;
  total_message: number;
  health: number;
  loaded_plugins: number;
  message_stats: { labels: string[]; data: number[] };
  msg_io_status: { labels: string[]; data: number[] };
  recent_activity: {
    title: string;
    desc: string;
    time: string;
    icon_color: string;
    icon: string;
  }[];
}

/** 事件查看器（event.json 追溯数据） */
export interface EventItem {
  time: string;
  level: string;
  desc: string;
  message: string;
  /** 格式化后的完整堆栈（traceback.format_exception 产物） */
  traceback: string | null;
  icon_color: string;
  icon: string;
}

export interface EventsData {
  total: number;
  events: EventItem[];
}

/** Bot 状态 */
export interface BotStatusData {
  status: "online" | "offline";
  cpu_percent?: number;
  memory_percent?: number;
  disk_percent?: number;
  system_version?: string;
}

/** 插件 */
/** 插件状态，与后端 PluginState 一一对应 */
export type PluginState =
  | "running"
  | "pending_enable"
  | "pending_remove"
  | "load_failed"
  | "disabled"
  | "not_installed";

export type PluginKind =
  "builtin" | "amrita_pkg" | "nonebot_pkg" | "local" | null;

/** 已安装插件条目（六态视图） */
export interface PluginEntry {
  module_name: string;
  name: string;
  state: PluginState;
  kind: PluginKind;
  version: string | null;
  project_link: string | null;
  path: string | null;
  error: string | null;
  /** 是否属于「被别的插件间接依赖」而豁免的 */
  is_dependency: boolean;
  /** 非空表示不可禁用/卸载，内容为原因 */
  protected_reason: string | null;
}

export interface PluginListData {
  plugins: PluginEntry[];
  summary: Record<string, number>;
}

/** 插件商店条目 */
export interface PluginStoreEntry {
  module_name: string;
  name: string;
  source: "nonebot" | "amrita";
  target: "amrita" | "nonebot";
  project_link: string | null;
  desc: string;
  author: string | null;
  homepage: string | null;
  tags: string[];
  is_official: boolean;
  type: string;
  supported_adapters: string[] | null;
  version: string | null;
  /** 版本号来源：pypi / cache / cache-expired / identity */
  version_source: string;
  /** 版本信息可能已经过期 */
  outdated: boolean;
  valid: boolean;
  /** 该条目当前的状态；商店接口会附带 */
  state: PluginState | null;
  /** 该插件对宿主环境的版本约束 */
  requires: Record<string, string>;
  /** 版本约束是否与当前环境相容 */
  compatible: boolean;
  /** 不相容时的说明 */
  incompatible_reason: string | null;
  /** 是否被当前运行时已注册的适配器支持（无适配器限制视为支持） */
  supported_by_current: boolean;
}

export interface PluginStoreData {
  plugins: PluginStoreEntry[];
  total: number;
  /** 被「当前适配器支持」这个筛选挡掉的数量，0 表示没开筛选 */
  hidden_by_adapter: number;
  page: number;
  size: number;
  warnings: string[];
  /** 当前运行时已注册的适配器 */
  adapters: { name: string; module: string }[];
}

/** 安装 / 卸载任务 */
export type PluginTaskState = "pending" | "running" | "succeeded" | "failed";

export interface PluginTask {
  id: string;
  action: "install" | "uninstall";
  package: string;
  module_name: string;
  target: string;
  state: PluginTaskState;
  error: string | null;
  created_at: number;
  finished_at: number | null;
  lines?: string[];
}

/** WebSocket plugins 频道推送的单条事件 */
export interface PluginTaskEvent {
  task: PluginTask;
  line: string | null;
}

/** 黑名单 */
export interface BlacklistEntry {
  id: string;
  reason: string;
  added_time: string;
}
export interface BlacklistData {
  groups: BlacklistEntry[];
  users: BlacklistEntry[];
}

/** 权限 */
export interface PermGroup {
  name: string;
  permissions: string;
}
export interface PermGroupListData {
  groups: PermGroup[];
}
export interface PermissionsDetailData {
  permissions: string;
  permission_groups: string[];
}

/** 数据库元信息 */
export interface DbMetaData {
  error?: string;
  db_info: Record<string, unknown>;
  connection_stats: Record<string, unknown>;
  cache_efficiency: Record<string, unknown>;
  table_activity: Record<string, unknown>[];
  index_usage: Record<string, unknown>[];
  lock_info: Record<string, unknown>[];
  query_stats: Record<string, unknown>[];
  collection_timestamp: string;
  db_type: string;
}

/** confedit schema 字段 */
export interface ConfeditField {
  name: string;
  description: string;
  type: string;
  literal_values: string[] | null;
  default: unknown;
  current_value: unknown;
}
export interface ConfeditSchemaData {
  plugin_name: string;
  class_name: string;
  fields: ConfeditField[];
  config: Record<string, unknown>;
  hash: string;
}
export interface ConfeditConfigData {
  config: Record<string, unknown>;
  hash: string;
}
export interface ConfeditListData {
  configs: { name: string; class_name: string }[];
}

/** 模型参数（对应后端 ModelConfig） */
export interface ChatModelConfig {
  /** TopK（部分模型适配器不支持） */
  top_k?: number;
  /** TopP */
  top_p?: number;
  /** 温度 */
  temperature?: number;
  /** 是否启用流式响应（逐字输出） */
  stream?: boolean;
  /** 是否支持多模态输入（如图片识别） */
  multimodal?: boolean;
  /** 是否剥离响应中的 think 标签 */
  cot_model?: boolean;
  [key: string]: unknown;
}

/** 聊天管理 */
export interface ChatModel {
  name: string;
  model: string;
  base_url: string;
  api_key: string;
  /** 是否已配置 API Key（敏感字段不回传，仅暴露状态） */
  has_api_key?: boolean;
  protocol: string;
  /** 注意力窗口（输入 token 预算）；留空 = 回退到 Core 全局兜底值 */
  max_context?: number | null;
  /** 响应输出预留 token 上限；留空 = 回退到 Core 全局兜底值 */
  max_output?: number | null;
  // NOTE: 目前不对单个预设计费，rate 字段需要时再恢复。
  config: ChatModelConfig;
  thinking_config: Record<string, unknown> | null;
}
export interface ChatModelsData {
  models: ChatModel[];
}
export interface ChatPrompt {
  name: string;
  text: string;
}
export interface ChatPromptsData {
  prompts: { group: ChatPrompt[]; private: ChatPrompt[] };
}
export interface McpServer {
  server_script: string;
  tools_count: number;
  status: "connected" | "disconnected";
}
export interface McpServersData {
  servers: McpServer[];
}
export interface SkillInfo {
  name: string;
  description: string;
  version: string | null;
  path: string;
  enabled: boolean;
  ok: boolean;
  error: string | null;
}
export interface SkillConfig {
  enable: boolean;
  /** 启用的技能名称列表（空列表=全部启用；非空则仅列表内的技能启用） */
  selected: string[];
}
export interface SkillsData {
  skills: SkillInfo[];
  config: SkillConfig;
}
export interface ChatInsightsData {
  token_prompt: number;
  token_completion: number;
  usage_count: number;
  chart_data: {
    date: string;
    token_input: number;
    token_output: number;
    usage_count: number;
  }[];
}

/** 配置文件 */
export interface BotConfigListData {
  files: string[];
  selected: string | null;
  content: string;
  /** Dotenv 编辑被禁用（NO_ENV_EDITOR=true） */
  disabled?: boolean;
}
export interface BotConfigData {
  content: string;
}
