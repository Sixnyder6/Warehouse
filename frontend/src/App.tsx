import React, { useState, useEffect } from 'react';
import { api, type AuthState } from './api';
import { triggerSync, db } from './db';
import { LoginView } from './components/LoginView';
import { DashboardView } from './components/DashboardView';
import { CatalogView } from './components/CatalogView';
import { OrdersView } from './components/OrdersView';
import { HistoryView } from './components/HistoryView';
import { UsersView } from './components/UsersView';
import { ImportExportView } from './components/ImportExportView';
import { ToastContainer, type ToastMessage } from './components/ToastContainer';

import {
  House,
  Package,
  ClipboardText,
  Clock,
  Users,
  SignOut,
  Play,
  Stop,
  WifiHigh,
  WifiSlash,
  SpinnerGap,
  FileArrowUp
} from '@phosphor-icons/react';

type TabType = 'dashboard' | 'catalog' | 'orders' | 'history' | 'users' | 'import';

// ==============================
// Global Error Boundary
// ==============================
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('🚨 React Error Boundary caught:', error, info);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          minHeight: '100vh', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          background: '#0f172a', color: '#f1f5f9', fontFamily: 'monospace',
          padding: '2rem', textAlign: 'center'
        }}>
          <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>🚨</div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 'bold', marginBottom: '0.5rem', color: '#f87171' }}>
            Ошибка рендеринга
          </h1>
          <p style={{ color: '#94a3b8', marginBottom: '1.5rem', maxWidth: '500px' }}>
            {this.state.error?.message || 'Неизвестная ошибка'}
          </p>
          <pre style={{
            background: '#1e293b', padding: '1rem', borderRadius: '0.5rem',
            fontSize: '0.75rem', color: '#cbd5e1', maxWidth: '600px',
            overflow: 'auto', maxHeight: '200px', textAlign: 'left',
            marginBottom: '1.5rem'
          }}>
            {this.state.error?.stack?.split('\n').slice(0, 6).join('\n')}
          </pre>
          <button
            onClick={() => { this.setState({ hasError: false, error: null }); window.location.reload(); }}
            style={{
              background: '#3b82f6', color: 'white', border: 'none',
              padding: '0.75rem 2rem', borderRadius: '0.5rem',
              cursor: 'pointer', fontWeight: 'bold', fontSize: '0.875rem'
            }}
          >
            🔄 Перезагрузить
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

const App: React.FC = () => {
  const [authState, setAuthState] = useState<AuthState>({
    is_logged_in: false,
    user_id: null,
    user_name: null,
    is_admin: false,
    role: 'user',
    error: null,
    is_loading: true,
    is_shift_active: false,
    shift_start_time: 0,
    is_allowed_to_work: false,
    shift_request_status: 'NONE',
    version_error: false
  });

  const [activeTab, setActiveTab] = useState<TabType>('dashboard');
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [syncing, setSyncing] = useState(false);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  // Read URL path to resolve initial tab
  const getTabFromPath = (path: string): TabType => {
    if (path.includes('/desktop/parts_list') || path.includes('/desktop/catalog')) return 'catalog';
    if (path.includes('/desktop/transactions') || path.includes('/desktop/orders')) return 'orders';
    if (path.includes('/desktop/history')) return 'history';
    if (path.includes('/desktop/users')) return 'users';
    if (path.includes('/desktop/import_export')) return 'import';
    return 'dashboard';
  };

  const getPathFromTab = (tab: TabType): string => {
    switch (tab) {
      case 'catalog': return '/desktop/catalog';
      case 'orders': return '/desktop/orders';
      case 'history': return '/desktop/history';
      case 'users': return '/desktop/users';
      case 'import': return '/desktop/import_export';
      default: return '/desktop/dashboard';
    }
  };

  const navigateToTab = (tab: TabType, searchParams?: string) => {
    setActiveTab(tab);
    const basePath = getPathFromTab(tab);
    const path = searchParams ? `${basePath}?${searchParams}` : basePath;
    window.history.pushState(null, '', path);
    window.dispatchEvent(new Event('popstate'));
  };

  const checkAuth = async () => {
    try {
      const state = await api.auth.getMe();
      setAuthState(prev => ({ ...prev, ...state, is_loading: false }));
      
      if (state.is_logged_in) {
        // Run initial synchronization
        setSyncing(true);
        triggerSync().catch(console.error).finally(() => setSyncing(false));
      }
    } catch (err: any) {
      console.error('Initial session check failed:', err);
      // Only force logout on explicit 401. Network errors / 429 / 5xx should NOT reset session.
      // This prevents being kicked out when the server restarts or is temporarily unavailable.
      const status = err?.response?.status;
      if (status === 401) {
        setAuthState(prev => ({ ...prev, is_logged_in: false, is_loading: false }));
      } else {
        // Keep current session state, just stop loading
        setAuthState(prev => ({ ...prev, is_loading: false }));
      }
    }
  };

  useEffect(() => {
    checkAuth();

    // Browser navigation (back/forward button) listener
    const handlePopState = () => {
      setActiveTab(getTabFromPath(window.location.pathname));
    };
    window.addEventListener('popstate', handlePopState);

    // Online check listeners
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    // Initial routing setup
    setActiveTab(getTabFromPath(window.location.pathname));

    return () => {
      window.removeEventListener('popstate', handlePopState);
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // Redirect non-administrative roles (muver, electrician, technic, security, user) to mobile dashboard
  useEffect(() => {
    if (authState.is_logged_in && authState.role) {
      const allowedRoles = ['admin', 'inventory_manager', 'supervisor'];
      if (!allowedRoles.includes(authState.role)) {
        console.log(`⚠️ User role ${authState.role} is not administrative. Redirecting to mobile dashboard.`);
        window.location.href = '/mobile/dashboard';
      }
    }
  }, [authState.is_logged_in, authState.role]);

  useEffect(() => {
    if (!authState.is_logged_in) return;

    let socket: WebSocket | null = null;
    let reconnectTimeout: number | null = null;

    const connectWebSocket = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/api/ws/sync`;
      
      console.log('🔗 Connecting WebSocket sync channel:', wsUrl);
      socket = new WebSocket(wsUrl);

      socket.onopen = () => {
        console.log('✅ WebSocket sync channel connected');
      };

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'toast_notification') {
            // Check if this action was triggered by the current user to avoid self-notifying
            if (data.userName === authState.user_name) return;

            let text = '';
            let toastType: 'take' | 'add' | 'info' = 'info';

            if (data.actionType === 'TAKE') {
              text = `${data.userName} списал(а) ${data.quantity} шт. «${data.itemName}»`;
              toastType = 'take';
            } else if (data.actionType === 'ADD') {
              text = `${data.userName} пополнил(а) «${data.itemName}» на +${data.quantity} шт.`;
              toastType = 'add';
            } else if (data.actionType === 'TAKE_EXTENDED') {
              text = `${data.userName} выдал(а) ${data.quantity} шт. «${data.itemName}» получателю ${data.recipientName}`;
              toastType = 'take';
            } else if (data.actionType === 'RETURN') {
              text = `${data.userName} вернул(а) ${data.quantity} шт. «${data.itemName}» от ${data.recipientName}`;
              toastType = 'add';
            } else {
              text = `${data.userName} обновил(а) складские остатки`;
            }

            // Push toast
            setToasts((prev) => [
              ...prev,
              {
                id: `ws_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
                message: text,
                type: toastType,
              },
            ]);

            // Automatically trigger sync in background to update the catalog in real-time
            setSyncing(true);
            triggerSync().finally(() => setSyncing(false));
          } else if (data.type === 'sync_notification') {
            // Push toast
            setToasts((prev) => [
              ...prev,
              {
                id: `ws_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
                message: `Пользователь ${data.userName} синхронизировал с сервером ${data.count} операций`,
                type: 'info',
              },
            ]);

            // Auto sync
            setSyncing(true);
            triggerSync().finally(() => setSyncing(false));
          }
        } catch (err) {
          console.error('Failed to parse websocket message:', err);
        }
      };

      socket.onerror = (err) => {
        console.warn('⚠️ WebSocket error:', err);
      };

      socket.onclose = (event) => {
        console.log('🔌 WebSocket connection closed. Reconnecting in 5s...', event.reason);
        reconnectTimeout = window.setTimeout(connectWebSocket, 5000);
      };
    };

    connectWebSocket();

    return () => {
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
      }
    };
  }, [authState.is_logged_in, authState.user_name]);

  const handleLoginSuccess = (state: AuthState) => {
    setAuthState(prev => ({ ...prev, ...state, is_loading: false }));
    navigateToTab('dashboard');
  };

  const handleLogout = async () => {
    if (!window.confirm('Вы действительно хотите выйти из системы?')) return;
    try {
      await api.auth.logout();
      // Clear Dexie database caches on logout to avoid cross-user details leakage
      await db.items.clear();
      await db.logs.clear();
      await db.orders.clear();
      await db.syncQueue.clear();
      
      setAuthState({
        is_logged_in: false,
        user_id: null,
        user_name: null,
        is_admin: false,
        role: 'user',
        error: null,
        is_loading: false,
        is_shift_active: false,
        shift_start_time: 0,
        is_allowed_to_work: false,
        shift_request_status: 'NONE',
        version_error: false
      });
      window.history.pushState(null, '', '/login');
    } catch (err) {
      console.error('Logout failed:', err);
    }
  };

  const handleToggleShift = async () => {
    if (!authState.user_id) return;
    try {
      let state;
      if (authState.is_shift_active) {
        state = await api.auth.endShift(authState.user_id);
      } else {
        state = await api.auth.startShift(authState.user_id);
      }
      setAuthState(state);
    } catch (err) {
      console.error('Failed to toggle shift state:', err);
      alert('Ошибка при управлении сменой');
    }
  };

  if (authState.is_loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50 text-slate-900">
        <SpinnerGap size={40} className="animate-spin text-blue-500 mb-4" />
        <span className="text-sm text-slate-500 font-medium tracking-wide">Проверка сеанса...</span>
      </div>
    );
  }

  // Not logged in -> Render login panel
  if (!authState.is_logged_in) {
    return <LoginView onLoginSuccess={handleLoginSuccess} />;
  }

  // Logged in -> Render visual SPA dashboard structure
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col md:flex-row font-sans selection:bg-blue-500/20 selection:text-blue-900">
      
      {/* 1. Left Sidebar menu column */}
      <aside className="w-full md:w-64 shrink-0 bg-white border-b md:border-b-0 md:border-r border-slate-200 shadow-sm flex flex-col justify-between p-5 relative z-20">
        <div className="space-y-8">
          {/* Brand header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center font-bold text-white text-base shadow-md shadow-blue-500/20">
                W
              </div>
              <span className="font-bold tracking-tight text-slate-800 font-sans text-base">Бестужевская 10</span>
            </div>
            {/* Tiny connection symbol */}
            <div className="flex items-center gap-2" title={isOnline ? 'Сеть активна' : 'Соединение потеряно'}>
              {syncing && <SpinnerGap size={16} className="animate-spin text-blue-400" />}
              {isOnline ? (
                <WifiHigh size={18} className="text-emerald-400" />
              ) : (
                <WifiSlash size={18} className="text-rose-500 animate-pulse" />
              )}
            </div>
          </div>

          {/* Nav links */}
          <nav className="space-y-1">
            <button
              onClick={() => navigateToTab('dashboard')}
              className={`w-full flex items-center gap-3 py-2.5 px-4 rounded-xl text-sm font-semibold transition-all cursor-pointer ${
                activeTab === 'dashboard' 
                  ? 'bg-blue-50 text-blue-700 shadow-sm' 
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
              }`}
            >
              <House size={20} className={activeTab === 'dashboard' ? 'text-blue-600' : ''} />
              <span>Рабочий стол</span>
            </button>

            <button
              onClick={() => navigateToTab('catalog')}
              className={`w-full flex items-center gap-3 py-2.5 px-4 rounded-xl text-sm font-semibold transition-all cursor-pointer ${
                activeTab === 'catalog' 
                  ? 'bg-blue-50 text-blue-700 shadow-sm' 
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
              }`}
            >
              <Package size={20} className={activeTab === 'catalog' ? 'text-blue-600' : ''} />
              <span>Детали и Каталог</span>
            </button>

            <button
              onClick={() => navigateToTab('orders')}
              className={`w-full flex items-center gap-3 py-2.5 px-4 rounded-xl text-sm font-semibold transition-all cursor-pointer ${
                activeTab === 'orders' 
                  ? 'bg-blue-50 text-blue-700 shadow-sm' 
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
              }`}
            >
              <ClipboardText size={20} className={activeTab === 'orders' ? 'text-blue-600' : ''} />
              <span>Заказы</span>
            </button>

            <button
              onClick={() => navigateToTab('history')}
              className={`w-full flex items-center gap-3 py-2.5 px-4 rounded-xl text-sm font-semibold transition-all cursor-pointer ${
                activeTab === 'history' 
                  ? 'bg-blue-50 text-blue-700 shadow-sm' 
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
              }`}
            >
              <Clock size={20} className={activeTab === 'history' ? 'text-blue-600' : ''} />
              <span>История</span>
            </button>

            <button
              onClick={() => navigateToTab('users')}
              className={`w-full flex items-center gap-3 py-2.5 px-4 rounded-xl text-sm font-semibold transition-all cursor-pointer ${
                activeTab === 'users' 
                  ? 'bg-blue-50 text-blue-700 shadow-sm' 
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
              }`}
            >
              <Users size={20} className={activeTab === 'users' ? 'text-blue-600' : ''} />
              <span>Смена команды</span>
            </button>

            <button
              onClick={() => navigateToTab('import')}
              className={`w-full flex items-center gap-3 py-2.5 px-4 rounded-xl text-sm font-semibold transition-all cursor-pointer ${
                activeTab === 'import' 
                  ? 'bg-blue-50 text-blue-700 shadow-sm' 
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
              }`}
            >
              <FileArrowUp size={20} className={activeTab === 'import' ? 'text-blue-600' : ''} />
              <span>Импорт/Экспорт</span>
            </button>
          </nav>
        </div>

        {/* 2. User profile card & shift controls (Bottom column) */}
        <div className="mt-8 pt-5 border-t border-slate-200 space-y-4">
          <div className="flex items-center gap-3 px-1">
            <div className="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center font-bold text-slate-500 border border-slate-200 uppercase">
              {authState.user_name?.substring(0, 2) || 'US'}
            </div>
            <div className="min-w-0 flex-1">
              <strong className="text-sm font-semibold text-slate-800 block truncate leading-tight">
                {authState.user_name}
              </strong>
              <span className="text-xxs text-slate-500 mt-0.5 block uppercase tracking-wider font-bold">
                {authState.role === 'admin' ? 'Администратор' : authState.role === 'inventory_manager' ? 'Менеджер' : 'Сотрудник'}
              </span>
            </div>
          </div>

          {/* Shift toggle controller */}
          <button
            onClick={handleToggleShift}
            className={`w-full py-2.5 px-4 rounded-xl text-xs font-bold flex items-center justify-center gap-2 border transition-all cursor-pointer ${
              authState.is_shift_active
                ? 'bg-rose-50 border-rose-200 text-rose-600 hover:bg-rose-100'
                : 'bg-emerald-50 border-emerald-200 text-emerald-600 hover:bg-emerald-100'
            }`}
          >
            {authState.is_shift_active ? (
              <>
                <Stop size={16} weight="fill" /> Закончить смену
              </>
            ) : (
              <>
                <Play size={16} weight="fill" /> Начать смену
              </>
            )}
          </button>

          {/* Logout */}
          <button
            onClick={handleLogout}
            className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold text-slate-500 hover:text-rose-600 hover:bg-rose-50 flex items-center justify-center gap-2 transition-all cursor-pointer border border-transparent hover:border-rose-100"
          >
            <SignOut size={16} /> Выйти
          </button>
        </div>
      </aside>

      {/* 2. Main Content Display Panel */}
      <main className="flex-1 bg-slate-50 p-6 md:p-8 overflow-y-auto max-h-screen">
        {activeTab === 'dashboard' && <DashboardView currentUserState={authState} onNavigate={navigateToTab} />}
        {activeTab === 'catalog' && <CatalogView currentUserState={authState} />}
        {activeTab === 'orders' && <OrdersView currentUserState={authState} />}
        {activeTab === 'history' && <HistoryView />}
        {activeTab === 'users' && <UsersView />}
        {activeTab === 'import' && <ImportExportView currentUserState={authState} />}
      </main>

      <ToastContainer
        toasts={toasts}
        onDismiss={(id) => setToasts((prev) => prev.filter((t) => t.id !== id))}
      />
    </div>
  );
};

export default App;

// Wrap App in ErrorBoundary at the module level so that
// any render crash shows a helpful error instead of a black screen.
export const AppWithErrorBoundary: React.FC = () => (
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);
