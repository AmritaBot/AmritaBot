/** 与后端 API 对应的类型定义 */

/** 菜单 / 路由注册表 */
export interface MenuRoute {
  path: string; // FastAPI 风格，如 /system/confedit/{owner_name}
  name: string;
  category: string;
  icon: string | null;
  hidden: boolean;
}

export interface MenuData {
  routes: MenuRoute[];
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
export interface PluginInfo {
  name: string;
  homepage: string | null;
  is_local: boolean;
  type: string;
  description: string;
  version: string;
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

/** 聊天管理 */
export interface ChatModel {
  name: string;
  model: string;
  base_url: string;
  api_key: string;
  protocol: string;
  config: Record<string, unknown>;
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
