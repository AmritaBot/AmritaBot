/**
 * WebSocket 实时数据 hook（全局单连接）
 *
 * - 连接 /amrita/ui/ws（同源，自动携带 cookie）
 * - 连接在模块级持有，整个应用共享一条 WS（切换页面不重连）
 * - 按频道订阅：system（系统资源 2s）/ bot（连接状态）/ logs（日志流）
 * - 断线自动重连（指数退避），断线/恢复时右下角 toast 提示
 *
 * logs 频道约定：
 * - 后端订阅时只回放最新 N 条（tail 语义，非全量），N 由本模块
 *   LOG_REPLAY_LIMIT / useWs 的 logLimit 决定，随订阅消息发送
 * - 快照按时间正序存储（最新在尾部），并截断到 MAX_LOG_SNAPSHOT，
 *   防止长运行下数组无限增长拖垮 UI（去重只查尾部：回放与实时
 *   推送的重叠只会出现在边界）
 */
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

export type WsChannel = "system" | "bot" | "logs";

/** 订阅 logs 时请求的回放条数（后端 tail 语义） */
export const LOG_REPLAY_LIMIT = 500;
/** 前端内存中保留的日志快照上限（超过则丢弃最旧） */
const MAX_LOG_SNAPSHOT = 1000;

export interface SystemUsage {
  status: string;
  cpu_usage?: number;
  memory_usage?: number;
  disk_usage?: number;
  network_io?: { sent: number; received: number };
  logical_cores?: number;
}

export interface BotState {
  status: "online" | "offline";
}

export interface LogEvent {
  title: string;
  desc: string;
  time: string;
  icon_color: string;
  icon: string;
}

export interface WsMeta {
  subscribed: string[];
  pong?: boolean;
}

type ChannelData = {
  system: SystemUsage;
  bot: BotState;
  logs: LogEvent;
  meta: WsMeta;
};

/* 全局单连接管理 */

interface GlobalState {
  ws: WebSocket | null;
  connected: boolean;
  everConnected: boolean; // 本次会话是否曾连上过（决定是否弹重连提示）
  retry: number;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
  reconnectToastId: string | number | null;
  /** 每个频道的最近数据（供新订阅者立即拿到快照） */
  snapshots: {
    system: SystemUsage | null;
    bot: BotState | null;
    logs: LogEvent[];
  };
  /** 频道 -> 订阅回调集合 */
  listeners: Map<WsChannel, Set<() => void>>;
  /** 连接状态监听器（onopen/onclose 时通知 useWs 更新 React state） */
  statusListeners: Set<(connected: boolean) => void>;
}

const global: GlobalState = {
  ws: null,
  connected: false,
  everConnected: false,
  retry: 0,
  reconnectTimer: null,
  reconnectToastId: null,
  snapshots: { system: null, bot: null, logs: [] },
  listeners: new Map(),
  statusListeners: new Set(),
};

/** 活动订阅者的日志回放条数登记表（token -> limit，仅在订阅 logs 且显式指定时登记）。
 *  连接级回放条数取所有活动订阅者的最大值；订阅者卸载时注销，条数随之回落，
 *  不会因某个订阅者请求过大值而永久抬高后续订阅者的回放量。 */
const logLimitSubscribers = new Map<number, number>();
let nextLogLimitToken = 0;

/** 当前连接生效的回放条数：所有活动订阅者的最大值，下限为默认值 LOG_REPLAY_LIMIT */
function effectiveLogLimit(): number {
  let limit = LOG_REPLAY_LIMIT;
  for (const l of logLimitSubscribers.values()) {
    if (l > limit) limit = l;
  }
  return limit;
}

function notifyStatus(connected: boolean) {
  global.statusListeners.forEach((cb) => cb(connected));
}

function emit(channel: WsChannel) {
  global.listeners.get(channel)?.forEach((cb) => cb());
}

function updateSnapshot<K extends keyof GlobalState["snapshots"]>(
  channel: K,
  data: GlobalState["snapshots"][K],
) {
  global.snapshots[channel] = data;
  emit(channel);
}

/** 发送订阅消息（订阅 logs 时附带连接级回放条数，后端按 tail 语义只回放最新 N 条） */
function sendSubscribe(ws: WebSocket, channels: WsChannel[]) {
  const msg: {
    action: string;
    channels: WsChannel[];
    opts?: { logs: { limit: number } };
  } = {
    action: "subscribe",
    channels,
  };
  if (channels.includes("logs")) {
    msg.opts = { logs: { limit: effectiveLogLimit() } };
  }
  ws.send(JSON.stringify(msg));
}

function connect() {
  // 清理待执行的重连 timer（防止多个 timer 并发 -> 多个 WS 连接）
  if (global.reconnectTimer !== null) {
    clearTimeout(global.reconnectTimer);
    global.reconnectTimer = null;
  }
  // CONNECTING 时等待现有连接，避免并发连接状态错乱
  if (
    global.ws &&
    (global.ws.readyState === WebSocket.OPEN ||
      global.ws.readyState === WebSocket.CONNECTING)
  ) {
    return;
  }

  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${window.location.host}/amrita/ui/ws`);
  global.ws = ws;

  ws.onopen = () => {
    global.retry = 0;
    global.connected = true;
    notifyStatus(true);
    // 恢复提示：先移除 loading 再弹独立 success（避免 id 更新失败导致 toast 堆积）
    if (global.everConnected && global.reconnectToastId !== null) {
      toast.dismiss(global.reconnectToastId);
      toast.success("实时连接已恢复");
      global.reconnectToastId = null;
    }
    global.everConnected = true;
    // 重新订阅所有频道
    const channels = [...global.listeners.keys()];
    if (channels.length > 0) {
      sendSubscribe(ws, channels);
    }
    emit("system");
    emit("bot");
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data as string) as {
        channel: keyof ChannelData;
        data: ChannelData[keyof ChannelData];
      };
      if (msg.channel === "system")
        updateSnapshot("system", msg.data as SystemUsage);
      else if (msg.channel === "bot")
        updateSnapshot("bot", msg.data as BotState);
      else if (msg.channel === "logs") {
        // 正序存储（最新在尾部，渲染即最早在上/最新在下，配合
        // 自动滚动到底 = tail -f 直觉）；去重只查尾部几条——后端
        // 回放与实时推送的重叠只会出现在边界；截断防无限增长
        const ev = msg.data as LogEvent;
        const logs = global.snapshots.logs;
        const dup = logs.slice(-10).some(
          (l) =>
            l.time === ev.time && l.title === ev.title && l.desc === ev.desc,
        );
        if (!dup) {
          updateSnapshot("logs", [...logs, ev].slice(-MAX_LOG_SNAPSHOT));
        }
      }
    } catch {
      // 忽略非 JSON 消息
    }
  };

  ws.onclose = (e) => {
    global.connected = false;
    global.ws = null;
    notifyStatus(false);
    // 未授权（4401：后端重启后内存态 token 失效）-> 停止重连，重连无意义
    if (e.code === 4401) {
      if (global.reconnectToastId !== null) {
        toast.dismiss(global.reconnectToastId);
        global.reconnectToastId = null;
      }
      toast.error("登录已过期，请重新登录");
      return;
    }
    // 曾连上过 -> 右下角提示正在重连（仅弹一次，复用 id）
    if (global.everConnected && global.reconnectToastId === null) {
      global.reconnectToastId = toast.loading("正在尝试重连…", {
        duration: Infinity,
      });
    }
    emit("system");
    emit("bot");
    // 指数退避重连
    const delay = Math.min(1000 * 2 ** global.retry, 15000);
    global.retry += 1;
    global.reconnectTimer = setTimeout(connect, delay);
  };

  ws.onerror = () => {
    ws.close();
  };
}

/* hook */

interface UseWsOptions {
  /** 订阅的频道 */
  channels: WsChannel[];
  /** 订阅 logs 时请求的回放条数（tail 语义；仅对当前订阅生效，连接级取活动订阅者的最大值） */
  logLimit?: number;
  /** 连接状态变化回调 */
  onStatusChange?: (connected: boolean) => void;
}

export function useWs({ channels, logLimit, onStatusChange }: UseWsOptions) {
  const [connected, setConnected] = useState(global.connected);
  const [system, setSystem] = useState<SystemUsage | null>(
    global.snapshots.system,
  );
  const [bot, setBot] = useState<BotState | null>(global.snapshots.bot);
  const [logs, setLogs] = useState<LogEvent[]>(global.snapshots.logs);

  // channels 引用不稳定（调用处每次渲染新建数组）-> 用稳定 key 做 effect 依赖
  const channelsKey = channels.join(",");
  const channelsRef = useRef(channels);
  channelsRef.current = channels;

  const onStatusChangeRef = useRef(onStatusChange);
  onStatusChangeRef.current = onStatusChange;

  // 登记/注销本订阅者的回放条数：仅订阅 logs 且显式指定时生效；
  // 卸载或 channels 变化时自动注销，避免请求过大值后永久抬高后续订阅者的回放量
  useEffect(() => {
    const token = ++nextLogLimitToken;
    if (channels.includes("logs") && logLimit !== undefined) {
      logLimitSubscribers.set(token, logLimit);
    }
    return () => {
      logLimitSubscribers.delete(token);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelsKey, logLimit]);

  useEffect(() => {
    // 注册连接状态监听（onopen/onclose 时同步 connected state）
    const cb = (c: boolean) => {
      setConnected(c);
      onStatusChangeRef.current?.(c);
    };
    global.statusListeners.add(cb);
    setConnected(global.connected);
    onStatusChangeRef.current?.(global.connected);
    return () => {
      global.statusListeners.delete(cb);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const current = channelsRef.current;
    // 注册频道监听
    const listeners = current.map((ch) => {
      const set = global.listeners.get(ch) ?? new Set<() => void>();
      global.listeners.set(ch, set);
      const cb = () => {
        if (ch === "system") setSystem(global.snapshots.system);
        else if (ch === "bot") setBot(global.snapshots.bot);
        else if (ch === "logs") setLogs(global.snapshots.logs);
      };
      set.add(cb);
      return { ch, set, cb };
    });

    // 订阅（若连接已开）
    if (global.ws?.readyState === WebSocket.OPEN) {
      sendSubscribe(global.ws, current);
    }

    // 建立连接
    connect();

    return () => {
      for (const { ch, set, cb } of listeners) {
        set.delete(cb);
        if (set.size === 0) global.listeners.delete(ch);
      }
      // 连接保持：不关闭全局 ws
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelsKey]);

  useEffect(() => {
    onStatusChangeRef.current?.(connected);
  }, [connected]);

  return { connected, system, bot, logs };
}
