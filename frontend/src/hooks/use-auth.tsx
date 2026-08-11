/**
 * 认证状态管理（Context Provider）
 * - 启动时拉取 /api/auth/me 判断登录态
 * - 401 全局触发 setUnauthorizedHandler -> 跳转登录页
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError, setUnauthorizedHandler } from "@/lib/api";
import type { AuthMe } from "@/lib/types";

interface AuthContextValue {
  user: AuthMe | null;
  loading: boolean;
  /** 后端检测到默认密码（HTTP 423）：WebUI 锁定，必须更换密码 */
  passwordLocked: boolean;
  /** 登录失败次数过多（401 + ui_sec_locked 标记）：UI 安全锁定 */
  uiSecLocked: boolean;
  login: (username: string, password: string) => Promise<AuthMe>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** 后端锁定码：仍在使用出厂默认密码时返回 423 */
const PASSWORD_LOCKED_CODE = 423;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [passwordLocked, setPasswordLocked] = useState(false);
  const [uiSecLocked, setUiSecLocked] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await api.get<AuthMe>("/api/auth/me");
      setUser(res.data);
      setPasswordLocked(false);
      setUiSecLocked(false);
    } catch (err) {
      setUser(null);
      if (err instanceof ApiError) {
        // 423 = 默认密码锁定，渲染专门的更换密码提示页
        if (err.code === PASSWORD_LOCKED_CODE) {
          setPasswordLocked(true);
        }
        // 401 + ui_sec_locked 标记 = 失败次数过多，渲染安全锁定页
        if (
          err.code === 401 &&
          (err.data as { ui_sec_locked?: boolean } | undefined)?.ui_sec_locked
        ) {
          setUiSecLocked(true);
        }
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    // 401 时仅清空登录态，由 App 根据 user 状态自动渲染登录页（首页即登录页）
    setUnauthorizedHandler(() => {
      setUser(null);
    });
    return () => setUnauthorizedHandler(null);
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.post<AuthMe>("/api/auth/login", {
      username,
      password,
    });
    setUser(res.data);
    return res.data;
  }, []);

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout");
    setUser(null);
    // 登出后回到首页（首页即登录页）
    window.location.href = "/";
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        passwordLocked,
        uiSecLocked,
        login,
        logout,
        refresh,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}
