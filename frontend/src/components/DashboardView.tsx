import React, { useState, useEffect } from 'react';
import { api, type DashboardSummary, type AuthState, type WarehouseItem, type ForecastItem, type NewsItem } from '../api';
import { triggerSync, registerSyncStateListener, db } from '../db';
import { AnimateCount } from './AnimateCount';
import { 
  Package, 
  Warning, 
  ClipboardText, 
  Clock, 
  Circle, 
  CloudCheck, 
  CloudWarning,
  ArrowsClockwise,
  Users,
  Database,
  Megaphone,
  Plus,
  PencilSimple,
  Trash,
  X
} from '@phosphor-icons/react';

interface DashboardViewProps {
  currentUserState: AuthState;
  onNavigate: (tab: 'dashboard' | 'catalog' | 'orders' | 'history' | 'users', searchParams?: string) => void;
}

export const DashboardView: React.FC<DashboardViewProps> = ({ currentUserState, onNavigate }) => {
  const [items, setItems] = useState<WarehouseItem[]>([]);
  const [summary, setSummary] = useState<DashboardSummary>({
    totalItems: 0,
    lowStockCount: 0,
    activeOrdersCount: 0,
    todayOperationsCount: 0,
    recentLogs: []
  });
  const [onlineUsers, setOnlineUsers] = useState<any[]>([]);
  const [telemetry, setTelemetry] = useState<any>({
    metrics: { reads: 0, writes: 0, cache_hits: 0, cache_misses: 0, online_users: 1 },
    quota_limit: 50000
  });
  const [syncing, setSyncing] = useState(false);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [forecast, setForecast] = useState<ForecastItem[]>([]);
  
  // States for Warehouse News
  const [news, setNews] = useState<NewsItem[]>([]);
  const [isNewsModalOpen, setIsNewsModalOpen] = useState(false);
  const [editingNews, setEditingNews] = useState<NewsItem | null>(null);
  const [newsTitle, setNewsTitle] = useState('');
  const [newsContent, setNewsContent] = useState('');
  const [newsTag, setNewsTag] = useState<'GENERAL' | 'TODAY' | 'TOMORROW' | 'URGENT'>('GENERAL');
  const [newsError, setNewsError] = useState<string | null>(null);
  const [savingNews, setSavingNews] = useState(false);

  const loadData = async () => {
    try {
      // 1. Load data from Dexie local cache first (instant)
      const cachedItems = await db.items.toArray();
      setItems(cachedItems);
      const localTotalItems = cachedItems.reduce((acc, i) => acc + i.stockCount, 0);
      const localLowStock = cachedItems.filter(i => i.stockCount < i.lowStockThreshold).length;

      
      const cachedOrders = await db.orders.toArray();
      const localActiveOrders = cachedOrders.filter(o => ['CREATED', 'PROCESSING', 'READY'].includes(o.status)).length;
      
      const cachedLogs = await db.logs.orderBy('timestamp').reverse().limit(5).toArray();

      setSummary(prev => ({
        ...prev,
        totalItems: localTotalItems,
        lowStockCount: localLowStock,
        activeOrdersCount: localActiveOrders,
        recentLogs: cachedLogs.length > 0 ? cachedLogs : prev.recentLogs
      }));

      // 2. Fetch fresh API data
      if (navigator.onLine) {
        const freshSummary = await api.dashboard.getSummary();
        setSummary(freshSummary);
        
        // Cache these logs in local DB
        if (freshSummary.recentLogs && freshSummary.recentLogs.length > 0) {
          await db.logs.bulkPut(freshSummary.recentLogs);
        }

        const users = await api.dashboard.getOnlineUsers();
        setOnlineUsers(users);

        if (currentUserState.role === 'admin' || currentUserState.role === 'inventory_manager') {
          const dbTelemetry = await api.dashboard.getDbTelemetry(currentUserState.role);
          setTelemetry(dbTelemetry);
        }

        // Load forecast
        api.dashboard.getForecast(30).then(setForecast).catch(() => {});

        // Fetch news
        api.news.list().then(setNews).catch((err) => console.error('Failed to load news:', err));
      }
    } catch (err) {
      console.error('Failed to load dashboard statistics:', err);
    }
  };

  useEffect(() => {
    loadData();

    // Register offline/online listener
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    // Register sync listener
    const unsubscribeSync = registerSyncStateListener((isSync) => {
      setSyncing(isSync);
      if (!isSync) {
        // Reload statistics after sync completes
        loadData();
      }
    });

    // Run active user ping heartbeat
    const heartbeat = setInterval(() => {
      if (navigator.onLine && currentUserState.user_id) {
        api.dashboard.ping(currentUserState.user_id).catch(() => {});
        // Refresh online users occasionally
        api.dashboard.getOnlineUsers().then(setOnlineUsers).catch(() => {});
      }
    }, 45000);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      clearInterval(heartbeat);
      unsubscribeSync();
    };
  }, [currentUserState]);

  const handleManualSync = async () => {
    if (!isOnline) return;
    setSyncing(true);
    await triggerSync();
    await loadData();
    setSyncing(false);
  };

  const openEditNewsModal = (newsItem: NewsItem | null) => {
    setEditingNews(newsItem);
    if (newsItem) {
      setNewsTitle(newsItem.title);
      setNewsContent(newsItem.content);
      setNewsTag(newsItem.tag);
    } else {
      setNewsTitle('');
      setNewsContent('');
      setNewsTag('GENERAL');
    }
    setNewsError(null);
    setIsNewsModalOpen(true);
  };

  const handleSaveNews = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newsTitle.trim() || !newsContent.trim()) return;

    setSavingNews(true);
    setNewsError(null);
    try {
      const newsData = {
        title: newsTitle.trim(),
        content: newsContent.trim(),
        tag: newsTag
      };

      if (editingNews) {
        await api.news.update(editingNews.id, newsData);
      } else {
        await api.news.create(newsData);
      }

      setIsNewsModalOpen(false);
      // Reload news
      const freshNews = await api.news.list();
      setNews(freshNews);
    } catch (err: any) {
      console.error('Failed to save news:', err);
      setNewsError(err?.response?.data?.detail || 'Не удалось сохранить новость');
    } finally {
      setSavingNews(false);
    }
  };

  const handleDeleteNews = async () => {
    if (!editingNews) return;
    if (!window.confirm('Вы действительно хотите удалить эту новость?')) return;

    setSavingNews(true);
    setNewsError(null);
    try {
      await api.news.delete(editingNews.id);
      setIsNewsModalOpen(false);
      // Reload news
      const freshNews = await api.news.list();
      setNews(freshNews);
    } catch (err: any) {
      console.error('Failed to delete news:', err);
      setNewsError(err?.response?.data?.detail || 'Не удалось удалить новость');
    } finally {
      setSavingNews(false);
    }
  };

  // Helper to format date relative or short time
  const formatTime = (isoString: string) => {
    try {
      const dt = new Date(isoString);
      return dt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '--:--';
    }
  };

  const calculateTelemetryProgress = () => {
    const reads = telemetry.metrics?.reads || 0;
    const limit = telemetry.quota_limit || 50000;
    return Math.min((reads / limit) * 100, 100);
  };

  const isManager = currentUserState.role === 'admin' || currentUserState.role === 'inventory_manager';

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Top Header Row */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 font-sans">Рабочий стол</h1>
          <p className="text-slate-500 text-sm mt-1">
            Сводные метрики склада Бестужевская 10 в реальном времени.
          </p>
        </div>

        {/* Sync Controls */}
        <div className="flex items-center gap-3 bg-white p-2.5 rounded-xl border border-slate-200 shadow-sm self-start md:self-auto">
          <div className="flex items-center gap-2">
            {isOnline ? (
              <span className="flex items-center gap-1.5 text-emerald-400 text-xs font-semibold px-2 py-1 bg-emerald-500/10 rounded-md border border-emerald-500/20">
                <CloudCheck size={16} /> В СЕТИ
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-amber-400 text-xs font-semibold px-2 py-1 bg-amber-500/10 rounded-md border border-amber-500/20">
                <CloudWarning size={16} /> ОФЛАЙН
              </span>
            )}
          </div>
          
          {isManager && (
            <button
              onClick={handleManualSync}
              disabled={syncing || !isOnline}
              className="flex items-center gap-1.5 bg-slate-100 hover:bg-slate-200 disabled:opacity-50 text-slate-600 font-medium py-1.5 px-3 rounded-lg text-xs transition-colors duration-150 cursor-pointer"
            >
              <ArrowsClockwise size={14} className={syncing ? 'animate-spin' : ''} />
              Синхронизировать
            </button>
          )}
        </div>
      </div>

      {/* Numerical Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Total Items */}
        <div className="glassmorphism-card p-6 rounded-2xl flex items-start gap-4">
          <div className="p-3 bg-blue-50 text-blue-600 rounded-xl border border-blue-100">
            <Package size={28} />
          </div>
          <div>
            <span className="text-slate-500 text-xs font-semibold uppercase tracking-wider block">Деталей на складе</span>
            <span className="text-3xl font-bold text-slate-800 mt-1 block">
              <AnimateCount value={summary.totalItems} />
            </span>
          </div>
        </div>

        {/* Low Stock Items */}
        <div className="glassmorphism-card p-6 rounded-2xl flex items-start gap-4">
          <div className={`p-3 rounded-xl border ${summary.lowStockCount > 0 ? 'bg-amber-50 text-amber-600 border-amber-100' : 'bg-slate-50 text-slate-500 border-slate-200'}`}>
            <Warning size={28} />
          </div>
          <div>
            <span className="text-slate-500 text-xs font-semibold uppercase tracking-wider block">Критические остатки</span>
            <span className={`text-3xl font-bold mt-1 block ${summary.lowStockCount > 0 ? 'text-amber-600' : 'text-slate-800'}`}>
              <AnimateCount value={summary.lowStockCount} />
            </span>
          </div>
        </div>

        {/* Active Orders */}
        <div className="glassmorphism-card p-6 rounded-2xl flex items-start gap-4">
          <div className="p-3 bg-purple-50 text-purple-600 rounded-xl border border-purple-100">
            <ClipboardText size={28} />
          </div>
          <div>
            <span className="text-slate-500 text-xs font-semibold uppercase tracking-wider block">Активные заказы</span>
            <span className="text-3xl font-bold text-slate-800 mt-1 block">
              <AnimateCount value={summary.activeOrdersCount} />
            </span>
          </div>
        </div>

        {/* Today's Transactions */}
        <div className="glassmorphism-card p-6 rounded-2xl flex items-start gap-4">
          <div className="p-3 bg-emerald-50 text-emerald-600 rounded-xl border border-emerald-100">
            <Clock size={28} />
          </div>
          <div>
            <span className="text-slate-500 text-xs font-semibold uppercase tracking-wider block">Сделки за сегодня</span>
            <span className="text-3xl font-bold text-slate-800 mt-1 block">
              <AnimateCount value={summary.todayOperationsCount} />
            </span>
          </div>
        </div>
      </div>

      {/* Main Widgets Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Side: Recent Activity & Telemetry */}
        <div className="lg:col-span-2 space-y-8">
          {/* Quick Access Grid */}
          <div className="glassmorphism rounded-2xl p-6 shadow-sm border border-slate-200 bg-white">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2 font-sans">
                <Package size={20} className="text-blue-500" />
                Быстрый доступ
              </h2>
              <button
                onClick={() => onNavigate('catalog')}
                className="text-xs text-blue-600 hover:text-blue-500 font-semibold cursor-pointer"
              >
                Весь каталог →
              </button>
            </div>

            {items.length === 0 ? (
              <div className="text-center py-8 text-slate-500 text-sm">
                Нет товаров для отображения.
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                {items.slice(0, 6).map((item) => (
                  <div 
                    key={item.id}
                    onClick={() => onNavigate('catalog', `search=${encodeURIComponent(item.shortName)}`)}
                    className="bg-slate-50 border border-slate-200 rounded-xl p-3 cursor-pointer hover:border-blue-400 hover:bg-white hover:shadow-sm transition-all duration-150 flex flex-col items-center justify-between text-center h-full group"
                  >
                    <div className="w-full h-16 bg-white rounded-lg flex items-center justify-center overflow-hidden mb-3 border border-slate-200">
                      {item.imageUrl ? (
                        <img src={item.imageUrl} alt="" className="object-contain w-full h-full p-2 group-hover:scale-105 transition-transform duration-200" />
                      ) : (
                        <Package size={24} className="text-slate-400" />
                      )}
                    </div>
                    <div className="w-full text-xs font-bold text-slate-800 truncate" title={item.shortName}>
                      {item.shortName}
                    </div>
                    <div className="text-xxs text-slate-500 font-mono mt-0.5 truncate w-full">
                      {item.sku || '—'}
                    </div>
                    <div className="text-xs font-extrabold text-blue-600 mt-2">
                      {item.stockCount} <span className="text-xxs font-normal text-slate-500">{item.unit}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Recent Activity Log */}
          <div className="glassmorphism rounded-2xl p-6 relative overflow-hidden shadow-sm border border-slate-200 bg-white">
            <h2 className="text-xl font-bold text-slate-800 mb-6 flex items-center gap-2 font-sans">
              <Clock size={20} className="text-blue-500" />
              Последняя активность
            </h2>

            {summary.recentLogs.length === 0 ? (
              <div className="text-center py-12 text-slate-500 text-sm">
                Нет недавней активности в журнале.
              </div>
            ) : (
              <div className="space-y-4">
                {summary.recentLogs.slice(0, 5).map((log, idx) => (
                  <div key={log.id || idx} className="flex items-center justify-between p-3.5 bg-slate-50 rounded-xl border border-slate-100 hover:bg-slate-100 hover:border-slate-200 transition-colors duration-150">
                    <div className="flex items-center gap-3">
                      <div className={`w-2.5 h-2.5 rounded-full ${log.quantityChange < 0 ? 'bg-rose-500' : 'bg-emerald-500 animate-pulse'}`}></div>
                      <div>
                        <span className="font-semibold text-sm text-slate-800">{log.itemName}</span>
                        <div className="text-xs text-slate-500 mt-0.5">
                          Оператор: <span className="text-slate-600 font-medium">{log.userName}</span>
                        </div>
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-4">
                      <span className={`text-sm font-semibold ${log.quantityChange < 0 ? 'text-rose-600' : 'text-emerald-600'}`}>
                        {log.quantityChange > 0 ? `+${log.quantityChange}` : log.quantityChange}
                      </span>
                      <span className="text-xs text-slate-500 font-mono">
                        {formatTime(log.timestamp)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Database Telemetry (Admins / Managers Only) */}
          {(currentUserState.role === 'admin' || currentUserState.role === 'inventory_manager') && (
            <div className="glassmorphism rounded-2xl p-6 shadow-sm border border-slate-200 bg-white">
              <h2 className="text-xl font-bold text-slate-800 mb-6 flex items-center gap-2 font-sans">
                <Database size={20} className="text-blue-500" />
                Монитор Google Firestore (Квоты)
              </h2>

              <div className="space-y-6">
                <div>
                  <div className="flex justify-between text-xs font-semibold uppercase tracking-wider mb-2">
                    <span className="text-slate-500">Чтения Firestore (24ч)</span>
                    <span className="text-slate-800 font-bold">{telemetry.metrics?.reads || 0} / {telemetry.quota_limit || 50000}</span>
                  </div>
                  <div className="w-full bg-slate-100 rounded-full h-2.5 border border-slate-200 overflow-hidden">
                    <div 
                      className={`h-full rounded-full transition-all duration-500 ${calculateTelemetryProgress() > 80 ? 'bg-rose-500' : calculateTelemetryProgress() > 50 ? 'bg-amber-500' : 'bg-blue-500'}`}
                      style={{ width: `${calculateTelemetryProgress()}%` }}
                    ></div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-4 text-center">
                  <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                    <span className="text-slate-500 text-xxs font-bold uppercase block">Записи</span>
                    <span className="text-lg font-bold text-slate-800 mt-1 block">{telemetry.metrics?.writes || 0}</span>
                  </div>
                  <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                    <span className="text-slate-500 text-xxs font-bold uppercase block">Кэш Hits</span>
                    <span className="text-lg font-bold text-emerald-600 mt-1 block">{telemetry.metrics?.cache_hits || 0}</span>
                  </div>
                  <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                    <span className="text-slate-500 text-xxs font-bold uppercase block">Кэш Misses</span>
                    <span className="text-lg font-bold text-rose-600 mt-1 block">{telemetry.metrics?.cache_misses || 0}</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right Side: Widgets */}
        <div className="space-y-8">
          {/* Новости склада */}
          <div className="glassmorphism rounded-2xl p-6 shadow-sm border border-slate-200 bg-white">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2 font-sans">
                <Megaphone size={20} className="text-blue-500" />
                Новости склада
              </h2>
              {isManager && (
                <button
                  onClick={() => openEditNewsModal(null)}
                  className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-500 font-semibold cursor-pointer py-1 px-2 hover:bg-blue-50 rounded-lg transition-colors border border-transparent hover:border-blue-100"
                >
                  <Plus size={14} /> Добавить
                </button>
              )}
            </div>

            {news.length === 0 ? (
              <div className="text-center py-8 text-slate-500 text-sm">
                Нет новостей на складе.
              </div>
            ) : (
              <div className="space-y-4 max-h-[360px] overflow-y-auto pr-1">
                {news.map((item) => {
                  let badgeColors = 'text-slate-600 bg-slate-50 border-slate-200';
                  let badgeText = 'Общее';
                  if (item.tag === 'URGENT') {
                    badgeColors = 'text-rose-600 bg-rose-50 border-rose-200';
                    badgeText = 'Срочно';
                  } else if (item.tag === 'TODAY') {
                    badgeColors = 'text-blue-600 bg-blue-50 border-blue-200';
                    badgeText = 'Сегодня';
                  } else if (item.tag === 'TOMORROW') {
                    badgeColors = 'text-emerald-600 bg-emerald-50 border-emerald-200';
                    badgeText = 'Завтра';
                  }
                  
                  return (
                    <div 
                      key={item.id} 
                      className="group relative p-4 bg-slate-50 rounded-xl border border-slate-200 transition-all duration-150 hover:bg-white hover:shadow-sm"
                    >
                      <div className="flex items-start justify-between gap-2 mb-1.5">
                        <h3 className="font-bold text-sm text-slate-800 pr-12 line-clamp-2">
                          {item.title}
                        </h3>
                        <span className={`text-xxs font-bold px-2 py-0.5 rounded border uppercase tracking-wider shrink-0 ${badgeColors}`}>
                          {badgeText}
                        </span>
                      </div>
                      <p className="text-xs text-slate-600 whitespace-pre-wrap leading-relaxed">
                        {item.content}
                      </p>
                      
                      {isManager && (
                        <button
                          onClick={() => openEditNewsModal(item)}
                          className="absolute right-3 bottom-3 opacity-0 group-hover:opacity-100 p-1.5 text-slate-400 hover:text-blue-600 hover:bg-slate-100 rounded-lg transition-all duration-150 cursor-pointer"
                          title="Редактировать"
                        >
                          <PencilSimple size={14} />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Online Employees Presence — only for managers */}
          {isManager && (
            <div className="glassmorphism rounded-2xl p-6 shadow-sm border border-slate-200 bg-white">
              <h2 className="text-xl font-bold text-slate-800 mb-6 flex items-center gap-2 font-sans">
                <Users size={20} className="text-blue-500" />
                Команда на смене
              </h2>

              {onlineUsers.length === 0 ? (
                <div className="text-center py-8 text-slate-500 text-sm">
                  Нет сотрудников в сети.
                </div>
              ) : (
                <div className="space-y-4 max-h-[360px] overflow-y-auto pr-1">
                  {onlineUsers.map((user) => (
                    <div key={user.userId} className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200">
                      <div className="flex items-center gap-3">
                        <div className="relative">
                          <div className="w-10 h-10 rounded-xl bg-slate-200 flex items-center justify-center font-bold text-sm text-slate-600 uppercase border border-slate-300">
                            {(user.displayName || user.username || 'US').substring(0, 2)}
                          </div>
                          {user.isOnline && (
                            <Circle size={10} weight="fill" className="absolute -bottom-0.5 -right-0.5 text-emerald-500 bg-white rounded-full border border-white animate-ping" />
                          )}
                        </div>
                        <div>
                          <span className="text-sm font-semibold text-slate-800 block leading-tight">{user.displayName || user.username || 'Без имени'}</span>
                          <span className="text-xs text-slate-500 mt-0.5 block">
                            {user.role === 'admin' ? 'Администратор' : user.role === 'inventory_manager' ? 'Менеджер' : 'Сотрудник'}
                          </span>
                        </div>
                      </div>

                      <div className="flex flex-col items-end gap-1">
                        {user.isShiftActive ? (
                          <span className="text-xxs font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-100 uppercase">
                            АКТИВЕН
                          </span>
                        ) : (
                          <span className="text-xxs font-bold text-slate-500 bg-slate-100 px-2 py-0.5 rounded border border-slate-200 uppercase">
                            Вне смены
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Forecast — Прогноз остатков */}
          <div className="glassmorphism rounded-2xl p-6 shadow-sm border border-slate-200 bg-white">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2 font-sans">
                <Warning size={20} className="text-amber-500" />
                Прогноз остатков
              </h2>
              <button
                onClick={() => onNavigate('catalog', 'forecast=true')}
                className="text-xs text-blue-600 hover:text-blue-500 font-semibold cursor-pointer"
              >
                Все →
              </button>
            </div>

            {forecast.length === 0 ? (
              <div className="text-center py-8 text-slate-500 text-sm">
                Загрузка прогноза...
              </div>
            ) : (
              <div className="space-y-4">
                {forecast
                  .filter(f => f.daysRemaining !== null && f.daysRemaining < 7)
                  .slice(0, 7)
                  .map((f) => {
                    const critical = f.daysRemaining !== null && f.daysRemaining < 3;
                    const warning = f.daysRemaining !== null && f.daysRemaining >= 3 && f.daysRemaining < 7;
                    const badgeColor = critical
                      ? 'text-rose-600 bg-rose-50 border-rose-200'
                      : warning
                        ? 'text-amber-600 bg-amber-50 border-amber-200'
                        : 'text-emerald-600 bg-emerald-50 border-emerald-200';
                    return (
                      <div 
                        key={f.itemId}
                        onClick={() => onNavigate('catalog', `search=${encodeURIComponent(f.sku || f.itemName)}`)}
                        className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200 hover:border-blue-400 hover:bg-white hover:shadow-sm transition-all duration-150 cursor-pointer"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="w-10 h-10 rounded-lg bg-white flex items-center justify-center shrink-0 border border-slate-200 overflow-hidden">
                            {f.imageUrl ? (
                              <img src={f.imageUrl} alt="" className="object-contain w-full h-full p-1" />
                            ) : (
                              <Package size={18} className="text-slate-400" />
                            )}
                          </div>
                          <div className="min-w-0">
                            <span className="font-bold text-xs text-slate-800 block truncate leading-tight">{f.itemName}</span>
                            <span className="text-xxs text-slate-500 mt-1 block font-mono truncate">
                              Ост: {f.stockCount} шт • ~{f.avgDailyConsumption.toFixed(1)}/день
                            </span>
                          </div>
                        </div>
                        
                        <div className="flex items-center gap-2 shrink-0 ml-3">
                          <span className={`text-xxs font-bold px-2 py-0.5 rounded border uppercase tracking-wider ${badgeColor}`}>
                            {f.daysRemaining !== null
                              ? (f.daysRemaining < 1 ? 'Сегодня' : `${Math.ceil(f.daysRemaining)} дн`)
                              : '∞'}
                          </span>
                        </div>
                      </div>
                    );
                  })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* News Edit/Create Modal */}
      {isNewsModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fade-in">
          <div 
            className="w-full max-w-lg bg-white rounded-2xl border border-slate-200 shadow-2xl p-6 relative"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setIsNewsModalOpen(false)}
              className="absolute right-4 top-4 p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
            >
              <X size={18} />
            </button>

            <h3 className="text-xl font-bold text-slate-900 mb-6">
              {editingNews ? 'Редактировать новость' : 'Новая новость'}
            </h3>

            <form onSubmit={handleSaveNews} className="space-y-5">
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
                  Заголовок
                </label>
                <input
                  type="text"
                  value={newsTitle}
                  onChange={(e) => setNewsTitle(e.target.value)}
                  placeholder="Введите заголовок"
                  maxLength={100}
                  required
                  className="w-full px-4 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/25 bg-slate-50 hover:bg-slate-50/50 transition-colors text-sm text-slate-800"
                />
              </div>

              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
                  Содержание
                </label>
                <textarea
                  value={newsContent}
                  onChange={(e) => setNewsContent(e.target.value)}
                  placeholder="Введите текст новости..."
                  rows={4}
                  required
                  className="w-full px-4 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/25 bg-slate-50 hover:bg-slate-50/50 transition-colors text-sm text-slate-800 resize-none"
                />
              </div>

              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
                  Категория (тег)
                </label>
                <div className="flex flex-wrap gap-2">
                  {(['GENERAL', 'TODAY', 'TOMORROW', 'URGENT'] as const).map((tag) => {
                    let btnStyle = 'border-slate-200 text-slate-600 hover:bg-slate-50 bg-white';
                    let activeStyle = '';
                    let label = 'Общее';
                    
                    if (tag === 'GENERAL') {
                      activeStyle = 'bg-slate-100 border-slate-400 text-slate-800 font-bold';
                    } else if (tag === 'TODAY') {
                      label = 'Сегодня';
                      activeStyle = 'bg-blue-50 border-blue-400 text-blue-700 font-bold';
                    } else if (tag === 'TOMORROW') {
                      label = 'Завтра';
                      activeStyle = 'bg-emerald-50 border-emerald-400 text-emerald-700 font-bold';
                    } else if (tag === 'URGENT') {
                      label = 'Срочно';
                      activeStyle = 'bg-rose-50 border-rose-400 text-rose-700 font-bold';
                    }

                    const isSelected = newsTag === tag;

                    return (
                      <button
                        key={tag}
                        type="button"
                        onClick={() => setNewsTag(tag)}
                        className={`px-3 py-1.5 rounded-xl border text-xs font-semibold cursor-pointer transition-all ${
                          isSelected ? activeStyle : btnStyle
                        }`}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {newsError && (
                <div className="text-xs font-semibold text-rose-600 bg-rose-50 border border-rose-200/50 p-3 rounded-xl">
                  {newsError}
                </div>
              )}

              <div className="flex items-center justify-between pt-2">
                {editingNews ? (
                  <button
                    type="button"
                    onClick={handleDeleteNews}
                    disabled={savingNews}
                    className="flex items-center gap-1.5 px-3 py-2 border border-rose-200 text-rose-600 hover:bg-rose-50 rounded-xl text-xs font-bold transition-all cursor-pointer disabled:opacity-50"
                  >
                    <Trash size={16} /> Удалить
                  </button>
                ) : (
                  <div />
                )}

                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setIsNewsModalOpen(false)}
                    disabled={savingNews}
                    className="px-4 py-2 border border-slate-200 text-slate-600 hover:bg-slate-50 rounded-xl text-xs font-bold transition-all cursor-pointer bg-white disabled:opacity-50"
                  >
                    Отмена
                  </button>
                  <button
                    type="submit"
                    disabled={savingNews || !newsTitle.trim() || !newsContent.trim()}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-bold transition-all shadow-md shadow-blue-500/10 cursor-pointer disabled:opacity-50"
                  >
                    {savingNews ? 'Сохранение...' : 'Сохранить'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};