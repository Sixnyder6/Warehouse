import React, { useState, useEffect } from 'react';
import { api, type WarehouseOrder, type AuthState } from '../api';
import { 
  ClipboardText, 
  Clock, 
  CheckCircle, 
  XCircle, 
  HourglassMedium,
  Check,
  User,
  Package
} from '@phosphor-icons/react';
import { triggerSync } from '../db';

interface OrdersViewProps {
  currentUserState: AuthState;
}

export const OrdersView: React.FC<OrdersViewProps> = ({ currentUserState }) => {
  const [orders, setOrders] = useState<WarehouseOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterTab, setFilterTab] = useState<'active' | 'archive'>('active');

  const loadOrders = async () => {
    setLoading(true);
    try {
      // Fetch orders list from backend
      const list = await api.orders.list(undefined, undefined, 100);
      setOrders(list);
    } catch (err) {
      console.error('Failed to load orders list:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadOrders();
    const interval = setInterval(loadOrders, 20000); // Poll orders list every 20s
    return () => clearInterval(interval);
  }, []);

  const handleUpdateStatus = async (orderId: string, status: 'PROCESSING' | 'READY' | 'CANCELLED') => {
    try {
      const res = await api.orders.updateStatus(orderId, status);
      if (res.success) {
        setOrders(prev => prev.map(o => o.id === orderId ? { ...o, status } : o));
      }
    } catch (err) {
      console.error('Failed to update order status:', err);
      alert('Ошибка обновления статуса заказа');
    }
  };

  const handleCompleteOrder = async (orderId: string) => {
    const managerName = currentUserState.user_name || 'Кладовщик';
    if (!window.confirm(`Выдать товары по заказу и списать их со склада? Операция будет выполнена от имени: ${managerName}`)) return;
    
    try {
      const res = await api.orders.complete(orderId, managerName);
      if (res.success) {
        // Fast local status update
        setOrders(prev => prev.map(o => o.id === orderId ? { ...o, status: 'COMPLETED' } : o));
        // Trigger sync to get fresh stock balances in local cache
        triggerSync().catch(console.error);
      }
    } catch (err: any) {
      console.error('Failed to complete order:', err);
      alert(err.response?.data?.detail || 'Ошибка выдачи заказа');
    }
  };

  // Filter orders based on tabs
  const filteredOrders = orders.filter(o => {
    if (filterTab === 'active') {
      return ['CREATED', 'PROCESSING', 'READY'].includes(o.status);
    } else {
      return ['COMPLETED', 'CANCELLED'].includes(o.status);
    }
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'CREATED':
        return (
          <span className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded-lg uppercase">
            <HourglassMedium size={14} /> Новый
          </span>
        );
      case 'PROCESSING':
        return (
          <span className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded-lg uppercase">
            <Clock size={14} /> В сборке
          </span>
        );
      case 'READY':
        return (
          <span className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 bg-purple-500/10 text-purple-400 border border-purple-500/20 rounded-lg uppercase animate-pulse">
            <CheckCircle size={14} /> Готов
          </span>
        );
      case 'COMPLETED':
        return (
          <span className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-lg uppercase">
            <Check size={14} /> Выдан
          </span>
        );
      default:
        return (
          <span className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 bg-slate-100 text-slate-500 border border-slate-200 rounded-lg uppercase">
            <XCircle size={14} /> Отменен
          </span>
        );
    }
  };

  const formatOrderTime = (isoString: string) => {
    try {
      const dt = new Date(isoString);
      return dt.toLocaleDateString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return '';
    }
  };

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Head section */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-800 font-sans">Заказы на выдачу</h1>
          <p className="text-slate-500 text-sm mt-1">
            Обработка заявок от монтажников и муверов на получение запчастей.
          </p>
        </div>

        {/* Tab Controls */}
        <div className="flex bg-white p-1 rounded-xl border border-slate-200 shadow-sm self-start sm:self-auto">
          <button
            onClick={() => setFilterTab('active')}
            className={`py-2 px-4 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 ${
              filterTab === 'active' ? 'bg-blue-50 text-blue-700 shadow-sm border border-slate-200' : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <ClipboardText size={16} /> Активные
          </button>
          <button
            onClick={() => setFilterTab('archive')}
            className={`py-2 px-4 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 ${
              filterTab === 'archive' ? 'bg-blue-50 text-blue-700 shadow-sm border border-slate-200' : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <CheckCircle size={16} /> Архив
          </button>
        </div>
      </div>

      {loading && orders.length === 0 ? (
        <div className="text-center py-20 text-slate-500 text-sm">
          Загрузка списка заказов...
        </div>
      ) : filteredOrders.length === 0 ? (
        <div className="text-center py-20 text-slate-500 text-sm border border-dashed border-slate-200 rounded-2xl bg-slate-50">
          Заказы отсутствуют
        </div>
      ) : (
        /* Orders list grid */
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {filteredOrders.map((order) => (
            <div 
              key={order.id} 
              className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm hover:shadow-md hover:border-slate-300 flex flex-col justify-between group transition-all duration-200"
            >
              <div>
                {/* Card Head */}
                <div className="flex items-start justify-between gap-3 mb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-slate-50 flex items-center justify-center border border-slate-200 text-slate-500">
                      <User size={18} />
                    </div>
                    <div>
                      <strong className="text-sm font-semibold text-slate-800 block leading-tight">{order.userName}</strong>
                      <span className="text-xxs text-slate-600 mt-0.5 block">{order.userRole === 'technic' ? 'Техник' : 'Мувер'}</span>
                    </div>
                  </div>
                  {getStatusBadge(order.status)}
                </div>

                <hr className="border-slate-100 my-3" />

                {/* Items list */}
                <div className="space-y-2.5 my-4">
                  {order.items.map((item, idx) => (
                    <div key={item.itemId || idx} className="flex items-center justify-between text-xs text-slate-600">
                      <span className="flex items-center gap-1.5">
                        <Package size={14} className="text-slate-400" />
                        {item.itemName}
                      </span>
                      <strong className="text-slate-800 font-bold">{item.quantity} {item.unit}</strong>
                    </div>
                  ))}
                </div>
              </div>

              {/* Card Bottom / Actions */}
              <div className="mt-6 pt-4 border-t border-slate-100">
                <div className="flex justify-between items-center text-slate-400 text-xxs font-mono mb-4">
                  <span>ID: {order.id.substring(0, 8)}</span>
                  <span>{formatOrderTime(order.createdAt)}</span>
                </div>

                {/* Status action buttons */}
                {filterTab === 'active' && (
                  <div className="flex gap-2">
                    {order.status === 'CREATED' && (
                      <>
                        <button
                          onClick={() => handleUpdateStatus(order.id, 'CANCELLED')}
                          className="flex-1 py-2 border border-slate-200 bg-white hover:border-rose-200 hover:bg-rose-50 text-slate-600 hover:text-rose-600 text-xs font-semibold rounded-xl transition-all cursor-pointer"
                        >
                          Отклонить
                        </button>
                        <button
                          onClick={() => handleUpdateStatus(order.id, 'PROCESSING')}
                          className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-xl transition-all cursor-pointer shadow-lg shadow-blue-500/20"
                        >
                          В сборку
                        </button>
                      </>
                    )}

                    {order.status === 'PROCESSING' && (
                      <>
                        <button
                          onClick={() => handleUpdateStatus(order.id, 'CANCELLED')}
                          className="py-2 px-3 border border-slate-200 bg-white hover:border-rose-200 hover:bg-rose-50 text-slate-600 hover:text-rose-600 text-xs font-semibold rounded-xl transition-all cursor-pointer"
                          title="Отменить"
                        >
                          <XCircle size={16} />
                        </button>
                        <button
                          onClick={() => handleUpdateStatus(order.id, 'READY')}
                          className="flex-1 py-2 bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold rounded-xl transition-all cursor-pointer shadow-lg shadow-amber-500/5"
                        >
                          Собрано
                        </button>
                      </>
                    )}

                    {order.status === 'READY' && (
                      <button
                        onClick={() => handleCompleteOrder(order.id)}
                        className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-xl transition-all cursor-pointer shadow-lg shadow-emerald-500/5 flex items-center justify-center gap-1"
                      >
                        <Check size={14} weight="bold" /> Выдать со склада
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
