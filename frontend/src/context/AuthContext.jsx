import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback
} from 'react';

import { authService } from '../api/authService';
import { configService } from '../api/configService';
import { setToken } from '../api/apiClient';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const token = localStorage.getItem('opsflow_token');

    if (!token) {
      setLoading(false);
      return;
    }

    try {
      const data = await authService.bootstrap();

      setUser(data.user);
      setConfig(data.config);
    } catch (e) {
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function login(identifier, password) {
    const u = await authService.login(
      identifier,
      password
    );

    setUser(u);

    const cfg = await configService.get();

    setConfig(cfg);

    return u;
  }

  function logout() {
    authService.logout();

    setUser(null);
    setConfig(null);
  }

  // Re-fetch config (applications / environments / …) so an application an
  // admin just added shows up in every dropdown without logging out.
  const refreshConfig = useCallback(async () => {
    try {
      const cfg = await configService.get();
      setConfig(cfg);
      return cfg;
    } catch (e) {
      return null;
    }
  }, []);

  const updateUser = useCallback(
    (nextUser) => setUser(nextUser),
    []
  );

  // DevOps Admin = role DevOps + power enabled
  const isAdmin =
    !!user &&
    user.role === 'DevOps' &&
    user.power;

  return (
    <AuthContext.Provider
      value={{
        user,
        config,
        loading,
        login,
        logout,
        isAdmin,
        refresh,
        refreshConfig,
        setConfig,
        updateUser
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);

  if (!ctx) {
    throw new Error(
      'useAuth must be used within AuthProvider'
    );
  }

  return ctx;
}