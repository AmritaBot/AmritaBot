/**
 * WebSocket 实时数据 hook（全局单连接）
 *
 * - 连接 /amrita/ui/ws（同源，自动携带 cookie）
 * - 连接在模块级持有，整个应用共享一条 WS（切换页面不重连）
 * - 按频道订阅：system（系统资源 2s）/ bot（连接状态）/ logs（日志流）
 * - 断线自动重连（指数退避），断线/恢复时右下角 toast 提示
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

export type WsChannel = "system" | "bot" | "logs";

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

/* ---------------- 全局单连接管理 ---------------- */

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
  /** 频道 → 订阅回调集合 */
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

function connect() {
  // 清理待执行的重连 timer（防止多个 timer 并发 → 多个 WS 连接）
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
      ws.send(JSON.stringify({ action: "subscribe", channels }));
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
      if (msg.channel === "system") updateSnapshot("system", msg.data as SystemUsage);
      else if (msg.channel === "bot") updateSnapshot("bot", msg.data as BotState);
      else if (msg.channel === "logs") {
        // 按 (time,title,desc) 去重（后端订阅回放 + 实时推送可能重叠），不截断
        const ev = msg.data as LogEvent;
        const exists = global.snapshots.logs.some(
          (l) => l.time === ev.time && l.title === ev.title && l.desc === ev.desc,
        );
        if (!exists) {
          updateSnapshot("logs", [ev, ...global.snapshots.logs]);
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
    // 未授权（4401：后端重启后内存态 token 失效）→ 停止重连，重连无意义
    if (e.code === 4401) {
      if (global.reconnectToastId !== null) {
        toast.dismiss(global.reconnectToastId);
        global.reconnectToastId = null;
      }
      toast.error("登录已过期，请重新登录");
      return;
    }
    // 曾连上过 → 右下角提示正在重连（仅弹一次，复用 id）
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

/* ---------------- React hook ---------------- */

interface UseWsOptions {
  /** 订阅的频道 */
  channels: WsChannel[];
  /** 连接状态变化回调 */
  onStatusChange?: (connected: boolean) => void;
}

export function useWs({ channels, onStatusChange }: UseWsOptions) {
  const [connected, setConnected] = useState(global.connected);
  const [system, setSystem] = useState<SystemUsage | null>(global.snapshots.system);
  const [bot, setBot] = useState<BotState | null>(global.snapshots.bot);
  const [logs, setLogs] = useState<LogEvent[]>(global.snapshots.logs);

  // channels 引用不稳定（调用处每次渲染新建数组）→ 用稳定 key 做 effect 依赖
  const channelsKey = channels.join(",");
  const channelsRef = useRef(channels);
  channelsRef.current = channels;

  const onStatusChangeRef = useRef(onStatusChange);
  onStatusChangeRef.current = onStatusChange;

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
      global.ws.send(JSON.stringify({ action: "subscribe", channels: current }));
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
