import React, { useState, useEffect } from 'react';
import { api, type InternalUser } from '../api';
import { db, triggerSync } from '../db';
import { 
  Phone,
  Timer, 
  Circle,
  Clock
} from '@phosphor-icons/react';

// Sub-component for ticking shift duration timer
const ShiftTimer: React.FC<{ startTimeMs: number }> = ({ startTimeMs }) => {
  const [elapsed, setElapsed] = useState('');

  useEffect(() => {
    const updateTimer = () => {
      const diffMs = Date.now() - startTimeMs;
      if (diffMs <= 0) {
        setElapsed('0м');
        return;
      }
      
      const diffSecs = Math.floor(diffMs / 1000);
      const hours = Math.floor(diffSecs / 3600);
      const minutes = Math.floor((diffSecs % 3600) / 60);

      if (hours > 0) {
        setElapsed(`${hours}ч ${minutes}м`);
      } else {
        setElapsed(`${minutes}м`);
      }
    };

    updateTimer();
    const interval = setInterval(updateTimer, 60000); // Update every minute
    return () => clearInterval(interval);
  }, [startTimeMs]);

  return <span className="font-mono">{elapsed}</span>;
};

export const UsersView: React.FC = () => {
  const [users, setUsers] = useState<InternalUser[]>([]);
  const [presenceMap, setPresenceMap] = useState<{[userId: string]: any}>({});
  const [loading, setLoading] = useState(true);
  const [roleFilter, setRoleFilter] = useState<'all' | 'muver' | 'electrician' | 'technic' | 'management'>('all');

  const loadLocalUsers = async () => {
    try {
      const localUsers = await db.employees.toArray();
      if (localUsers.length > 0) {
        setUsers(localUsers);
      }
    } catch (err) {
      console.error('Failed to load users from IndexedDB:', err);
    }
  };

  const fetchPresence = async () => {
    try {
      const presenceList = await api.employees.listPresence();
      const map: {[userId: string]: any} = {};
      presenceList.forEach((p: any) => {
        if (p.id) {
          map[p.id] = p;
        }
      });
      setPresenceMap(map);
    } catch (err) {
      console.error('Failed to fetch user presence:', err);
    }
  };

  useEffect(() => {
    const init = async () => {
      // 1. Мгновенно показываем данные из IndexedDB
      await loadLocalUsers();
      await fetchPresence();
      setLoading(false); // ← показываем UI сразу, не ждём sync

      // 2. Синхронизируем в фоне, потом обновляем список
      triggerSync()
        .then(() => loadLocalUsers())
        .catch(console.error);
    };

    init();
    const interval = setInterval(fetchPresence, 60000); // Poll presence every 60s
    return () => clearInterval(interval);
  }, []);

  const getRoleLabel = (role: string) => {
    switch (role) {
      case 'admin':
        return 'Админ';
      case 'inventory_manager':
        return 'Менеджер';
      case 'muver':
        return 'Мувер';
      case 'electrician':
        return 'Электрик';
      case 'technic':
        return 'Техник';
      default:
        return 'Сотрудник';
    }
  };


  const getPresenceState = (lastSeen?: number) => {
    if (!lastSeen) return { text: 'офлайн', dotClass: 'text-slate-600' };
    const elapsed = Date.now() - lastSeen;
    const ONLINE_THRESHOLD = 3 * 60 * 1000;
    const AWAY_THRESHOLD = 15 * 60 * 1000;
    
    if (elapsed < ONLINE_THRESHOLD) {
      return { text: 'в сети', dotClass: 'text-emerald-500 animate-pulse' };
    } else if (elapsed < AWAY_THRESHOLD) {
      return { text: 'неактивен', dotClass: 'text-amber-500 animate-pulse' };
    } else {
      return { text: 'офлайн', dotClass: 'text-slate-600' };
    }
  };

  const formatLastSeen = (lastSeen?: number) => {
    if (!lastSeen) return 'ни разу';
    const state = getPresenceState(lastSeen);
    if (state.text === 'в сети') return 'в сети';
    if (state.text === 'неактивен') return 'неактивен';

    const diffMins = Math.floor((Date.now() - lastSeen) / 60000);
    if (diffMins <= 0) return '1 мин. назад';
    if (diffMins < 60) return `${diffMins} мин. назад`;
    
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} ч. назад`;

    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} дн. назад`;
  };

  // Merge static user profiles with dynamic presence state
  const mergedUsers = users.map(u => {
    const presence = presenceMap[u.id];
    if (presence) {
      return {
        ...u,
        lastSeen: presence.lastSeen,
        isShiftActive: presence.isShiftActive,
        shiftStartTime: presence.shiftStartTime,
        scansToday: presence.scansToday,
        batchesToday: presence.batchesToday,
        scanRatePerHour: presence.scanRatePerHour,
      };
    }
    return u;
  });

  // Filter users based on tabs
  const filteredUsers = mergedUsers.filter(user => {
    if (roleFilter === 'all') return true;
    if (roleFilter === 'management') {
      return user.role === 'admin' || user.role === 'inventory_manager';
    }
    return user.role === roleFilter;
  });

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Title */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-800 font-sans">Команда склада</h1>
          <p className="text-slate-500 text-sm mt-1">
            Мониторинг смен и активности сотрудников в реальном времени.
          </p>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap bg-white p-1 rounded-xl border border-slate-200 shadow-sm">
          {(['all', 'muver', 'electrician', 'technic', 'management'] as const).map((r) => (
            <button
              key={r}
              onClick={() => setRoleFilter(r)}
              className={`py-1.5 px-3 rounded-lg text-xxs font-bold uppercase tracking-wider transition-all cursor-pointer ${
                roleFilter === r ? 'bg-blue-50 text-blue-700 shadow-sm border border-slate-200' : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              {r === 'all' ? 'все' : r === 'muver' ? 'муверы' : r === 'electrician' ? 'электрики' : r === 'technic' ? 'техники' : 'менеджеры'}
            </button>
          ))}
        </div>
      </div>

      {loading && users.length === 0 ? (
        <div className="text-center py-20 text-slate-500 text-sm">
          Загрузка списка команды...
        </div>
      ) : filteredUsers.length === 0 ? (
        <div className="text-center py-20 text-slate-500 text-sm border border-dashed border-slate-200 rounded-2xl bg-slate-50">
          Сотрудники не найдены
        </div>
      ) : (
        /* Users Card Grid */
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredUsers.map((user) => {
            const presence = getPresenceState(user.lastSeen);
            const activeShift = user.isShiftActive;
            const shiftStart = user.shiftStartTime && user.shiftStartTime > 0
              ? user.shiftStartTime
              : (user.lastSeen ? user.lastSeen - 60000 : Date.now());
            
            return (
              <div 
                key={user.id} 
                className="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm flex flex-col justify-between hover:border-slate-300 hover:shadow-md transition-all duration-200"
              >
                <div>
                  {/* Card head: Avatar + Network check indicator */}
                  <div className="flex items-start justify-between gap-3 mb-4">
                    <div className="relative">
                      <div className="w-12 h-12 rounded-2xl bg-slate-50 border border-slate-200 flex items-center justify-center text-slate-500 font-bold uppercase text-base">
                        {(user.displayName || user.username || 'US').substring(0, 2)}
                      </div>
                      <Circle 
                        size={12} 
                        weight="fill" 
                        className={`absolute -bottom-0.5 -right-0.5 rounded-full border border-white bg-white ${presence.dotClass}`} 
                      />
                    </div>

                    <span className={`text-xxs font-bold uppercase px-2 py-0.5 rounded border ${
                      user.role === 'admin' 
                        ? 'bg-purple-50 text-purple-600 border-purple-200' 
                        : user.role === 'inventory_manager' 
                        ? 'bg-blue-50 text-blue-600 border-blue-200'
                        : 'bg-slate-100 text-slate-500 border-slate-200'
                    }`}>
                      {getRoleLabel(user.role)}
                    </span>
                  </div>

                  {/* Name, handle, and scans statistics */}
                  <div className="flex justify-between items-start mt-2">
                    <div className="truncate pr-2">
                      <strong className="text-slate-800 font-bold text-sm block truncate leading-tight mb-1">{user.displayName || user.username || 'Без имени'}</strong>
                      <span className="text-xs text-slate-500 font-mono block">@{user.username || 'user'}</span>
                    </div>
                    
                    {/* Scans stats (equivalent to Android team card list) */}
                    <div className="flex flex-col items-end shrink-0">
                      <span className={`text-xl font-bold tracking-tight leading-none ${user.scansToday && user.scansToday > 0 ? 'text-slate-800' : 'text-slate-600'}`}>
                        {user.scansToday || 0}
                      </span>
                      <span className="text-[10px] text-slate-500 font-medium mt-0.5">сканов</span>
                      {user.scanRatePerHour && user.scanRatePerHour > 0 ? (
                        <span className="mt-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-600 border border-emerald-200">
                          {user.scanRatePerHour}/ч
                        </span>
                      ) : null}
                    </div>
                  </div>

                  {user.phone && (
                    <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
                      <Phone size={14} className="text-slate-400" />
                      <a href={`tel:${user.phone}`} className="hover:text-blue-600 transition-colors">{user.phone}</a>
                    </div>
                  )}
                </div>

                <div className="mt-6 pt-4 border-t border-slate-100 space-y-3">
                  {/* Presence indicator details */}
                  <div className="flex items-center justify-between text-xs text-slate-500">
                    <span className="flex items-center gap-1.5 text-slate-400">
                      <Clock size={14} /> Активность
                    </span>
                    <span className={`font-medium ${presence.text !== 'офлайн' ? 'text-emerald-600 font-semibold' : 'text-slate-500'}`}>
                      {formatLastSeen(user.lastSeen)}
                    </span>
                  </div>

                  {/* Shift timer duration indicator */}
                  <div className="flex items-center justify-between text-xs">
                    <span className="flex items-center gap-1.5 text-slate-400">
                      <Timer size={14} /> Смена
                    </span>
                    {activeShift ? (
                      <span className="text-emerald-600 font-semibold flex items-center gap-1">
                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 animate-ping"></span>
                        <ShiftTimer startTimeMs={shiftStart} />
                      </span>
                    ) : (
                      <span className="text-slate-500 font-medium">Закрыта</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
