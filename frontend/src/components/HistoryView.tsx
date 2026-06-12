import React, { useState, useEffect } from 'react';
import { api, type Employee } from '../api';
import { db, triggerSync } from '../db';
import { 
  Chart as ChartJS, 
  CategoryScale, 
  LinearScale, 
  BarElement, 
  PointElement,
  LineElement,
  Title, 
  Tooltip, 
  Legend,
  Filler
} from 'chart.js';
import { Bar } from 'react-chartjs-2';
import { 
  Calendar, 
  User, 
  ListBullets, 
  ChartPieSlice, 
  ArrowUpRight, 
  ArrowDownLeft, 
  TrendUp,
  Clock,
  MagnifyingGlass,
  Funnel
} from '@phosphor-icons/react';

// Register Chart.js components
ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

export const HistoryView: React.FC = () => {
  const [operations, setOperations] = useState<any[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [stats, setStats] = useState<{ dates: string[]; counts: number[] }>({ dates: [], counts: [] });
  const [summaryData, setSummaryData] = useState<any>({ perEmployee: [], totals: [], grandTotal: 0 });
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'list' | 'summary'>('list');

  // Filter Parameters
  const [selectedEmployee, setSelectedEmployee] = useState('');
  const [period, setPeriod] = useState<'today' | 'week' | 'month' | 'custom'>('week');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const computeDates = (selectedPeriod: string) => {
    const now = new Date();
    let from = '';
    let to = now.toISOString().split('T')[0];

    if (selectedPeriod === 'today') {
      from = now.toISOString().split('T')[0];
    } else if (selectedPeriod === 'week') {
      const weekAgo = new Date();
      weekAgo.setDate(now.getDate() - 7);
      from = weekAgo.toISOString().split('T')[0];
    } else if (selectedPeriod === 'month') {
      const monthAgo = new Date();
      monthAgo.setMonth(now.getMonth() - 30); // 30 days exactly
      from = monthAgo.toISOString().split('T')[0];
    }

    return { from, to };
  };

  const fetchHistory = async () => {
    setLoading(true);
    try {
      let fromStr = dateFrom;
      let toStr = dateTo;

      if (period !== 'custom') {
        const calculated = computeDates(period);
        fromStr = calculated.from;
        toStr = calculated.to;
      }

      // Read operations from local IndexedDB
      let localOps = await db.logs.toArray();

      // Sort by timestamp DESC (newest first)
      localOps.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

      // Filter by employee
      if (selectedEmployee) {
        const emp = employees.find(e => e.id === selectedEmployee);
        const empName = emp ? emp.name : '';
        localOps = localOps.filter(op => 
          op.userId === selectedEmployee ||
          op.issuerId === selectedEmployee ||
          op.recipientId === selectedEmployee ||
          (empName && op.userName && op.userName.toLowerCase().includes(empName.toLowerCase())) ||
          (empName && op.issuerName && op.issuerName.toLowerCase().includes(empName.toLowerCase())) ||
          (empName && op.recipientName && op.recipientName.toLowerCase().includes(empName.toLowerCase()))
        );
      }

      // Filter by Search Query
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase().trim();
        localOps = localOps.filter(op => 
          (op.itemName && op.itemName.toLowerCase().includes(query)) ||
          (op.userName && op.userName.toLowerCase().includes(query)) ||
          (op.notes && op.notes.toLowerCase().includes(query))
        );
      }

      // Filter by date range
      if (fromStr) {
        const [y, m, d] = fromStr.split('-').map(Number);
        const fromDate = new Date(y, m - 1, d, 0, 0, 0, 0);
        localOps = localOps.filter(op => new Date(op.timestamp) >= fromDate);
      }
      if (toStr) {
        const [y, m, d] = toStr.split('-').map(Number);
        const toDate = new Date(y, m - 1, d, 23, 59, 59, 999);
        localOps = localOps.filter(op => new Date(op.timestamp) <= toDate);
      }

      // Compute stats for charts (using the filtered range)
      let statsOps = await db.logs.toArray();
      if (fromStr) {
        const [y, m, d] = fromStr.split('-').map(Number);
        const fromDate = new Date(y, m - 1, d, 0, 0, 0, 0);
        statsOps = statsOps.filter(op => new Date(op.timestamp) >= fromDate);
      }
      if (toStr) {
        const [y, m, d] = toStr.split('-').map(Number);
        const toDate = new Date(y, m - 1, d, 23, 59, 59, 999);
        statsOps = statsOps.filter(op => new Date(op.timestamp) <= toDate);
      }

      const dayCounts: { [key: string]: number } = {};
      statsOps.forEach(op => {
        if (op.timestamp) {
          const dt = new Date(op.timestamp);
          const year = dt.getFullYear();
          const month = String(dt.getMonth() + 1).padStart(2, '0');
          const day = String(dt.getDate()).padStart(2, '0');
          const dateKey = `${year}-${month}-${day}`;
          dayCounts[dateKey] = (dayCounts[dateKey] || 0) + 1;
        }
      });

      const sortedDates = Object.keys(dayCounts).sort();
      const counts = sortedDates.map(d => dayCounts[d]);

      // Compute summary (for active operations: takes/returns)
      const totalsMap: { [itemName: string]: number } = {};
      const perEmployeeMap: { [userName: string]: { [itemName: string]: number } } = {};

      localOps.forEach(op => {
        const userName = op.issuerName || op.userName || 'Неизвестный сотруд.';
        const itemName = op.itemName || 'Неизвестный товар';
        // Treat both takes and returns appropriately in summary. For absolute turnover we use abs().
        const quantity = Math.abs(op.quantityChange);

        totalsMap[itemName] = (totalsMap[itemName] || 0) + quantity;

        if (!perEmployeeMap[userName]) {
          perEmployeeMap[userName] = {};
        }
        perEmployeeMap[userName][itemName] = (perEmployeeMap[userName][itemName] || 0) + quantity;
      });

      const grandTotal = Object.values(totalsMap).reduce((sum, q) => sum + q, 0);

      const totalsList = Object.entries(totalsMap)
        .map(([itemName, totalQuantity]) => ({ itemName, totalQuantity }))
        .sort((a, b) => b.totalQuantity - a.totalQuantity);

      const perEmployeeList = Object.entries(perEmployeeMap)
        .map(([userName, itemsMap]) => {
          const items = Object.entries(itemsMap)
            .map(([itemName, totalQuantity]) => ({ itemName, totalQuantity }))
            .sort((a, b) => b.totalQuantity - a.totalQuantity);
          return { userName, items };
        })
        .sort((a, b) => {
          const aSum = a.items.reduce((sum, i) => sum + i.totalQuantity, 0);
          const bSum = b.items.reduce((sum, i) => sum + i.totalQuantity, 0);
          return bSum - aSum;
        });

      setOperations(localOps);
      setStats({ dates: sortedDates, counts });
      setSummaryData({ totals: totalsList, perEmployee: perEmployeeList, grandTotal });
    } catch (err) {
      console.error('Failed to load transaction history from local DB:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadEmployees = async () => {
    try {
      const localEmployees = await db.employees.toArray();
      if (localEmployees.length > 0) {
        const mapped = localEmployees.map(emp => ({
          id: emp.id,
          name: emp.displayName || emp.username,
          role: emp.role,
          phone: emp.phone
        }));
        setEmployees(mapped);
      } else {
        const fresh = await api.employees.listInternal();
        const mapped = fresh.map(emp => ({
          id: emp.id,
          name: emp.displayName || emp.username,
          role: emp.role,
          phone: emp.phone
        }));
        setEmployees(mapped);
      }
    } catch (err) {
      console.error('Failed loading employees', err);
    }
  };

  useEffect(() => {
    const init = async () => {
      // 1. Показываем данные из IndexedDB сразу (мгновенно, без ожидания sync)
      await loadEmployees();
      await fetchHistory(); // здесь loading станет false, UI виден

      // 2. Запускаем sync в фоне — ТОЛЬКО ПОСЛЕ чтения, чтобы не было конкурентных чтение+записи Dexie
      triggerSync()
        .then(async () => {
          await loadEmployees();
          await fetchHistory();
        })
        .catch(console.error);
    };

    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEmployee, period, dateFrom, dateTo, searchQuery]);

  // Chart configuration
  const chartData = {
    labels: stats.dates.map(date => {
      try {
        const parts = date.split('-');
        return `${parts[2]}.${parts[1]}`;
      } catch {
        return date;
      }
    }),
    datasets: [
      {
        label: 'Операции',
        data: stats.counts,
        backgroundColor: 'rgba(56, 189, 248, 0.2)', // Light blue fill
        borderColor: 'rgba(56, 189, 248, 0.8)',
        borderWidth: 2,
        borderRadius: 4,
        barPercentage: 0.5,
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(15, 23, 42, 0.9)',
        titleColor: '#f8fafc',
        bodyColor: '#cbd5e1',
        borderColor: 'rgba(255, 255, 255, 0.1)',
        borderWidth: 1,
        padding: 12,
        cornerRadius: 12,
        displayColors: false,
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { color: '#64748b', font: { size: 11, family: 'Inter' } },
      },
      y: {
        grid: { color: 'rgba(255, 255, 255, 0.05)' },
        ticks: { color: '#64748b', font: { size: 11, family: 'Inter' }, stepSize: 1 },
      },
    },
  };

  // Helper to format ISO datetime beautifully
  const formatDateTime = (isoString: string) => {
    try {
      const dt = new Date(isoString);
      return {
        date: dt.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' }),
        time: dt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
      };
    } catch {
      return { date: '—', time: '—' };
    }
  };

  return (
    <div className="space-y-6 md:space-y-8 animate-fade-in pb-12">
      {/* Header Area */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl md:text-4xl font-black tracking-tight text-slate-800 mb-2 flex items-center gap-3">
            История
          </h1>
          <p className="text-slate-500 text-sm max-w-lg leading-relaxed">
            Полный контроль за движениями по складу: выдачи, возвраты и пополнения товаров.
          </p>
        </div>
      </div>

      {/* Filter and Control Toolbar (Glassmorphism) */}
      <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm p-1.5 md:p-2">
        <div className="absolute inset-0 bg-gradient-to-br from-blue-50/50 to-purple-50/50 pointer-events-none" />
        
        <div className="relative flex flex-col xl:flex-row gap-3 xl:items-center justify-between p-3">
          
          <div className="flex flex-col md:flex-row items-center gap-3 w-full xl:w-auto">
            {/* Search Input */}
            <div className="flex items-center gap-2 bg-slate-50 hover:bg-slate-100 transition-colors px-4 py-2.5 rounded-2xl border border-slate-200 w-full md:w-64 focus-within:border-blue-500/50 focus-within:ring-1 focus-within:ring-blue-500/50 shadow-sm">
              <MagnifyingGlass size={18} className="text-slate-400" />
              <input
                type="text"
                placeholder="Поиск по товару..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-transparent text-slate-800 text-sm w-full focus:outline-none placeholder:text-slate-400"
              />
            </div>

            {/* Employee Filter */}
            <div className="flex items-center gap-2 bg-slate-50 hover:bg-slate-100 transition-colors px-4 py-2.5 rounded-2xl border border-slate-200 w-full md:w-56 cursor-pointer shadow-sm">
              <User size={18} className="text-slate-400" />
              <select
                value={selectedEmployee}
                onChange={(e) => setSelectedEmployee(e.target.value)}
                className="bg-transparent text-slate-800 text-sm w-full focus:outline-none border-none cursor-pointer appearance-none"
              >
                <option value="" className="bg-white">Все сотрудники</option>
                {employees.map(emp => (
                  <option key={emp.id} value={emp.id} className="bg-white">{emp.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row items-center gap-3 w-full xl:w-auto">
            {/* Period Segmented Control */}
            <div className="flex bg-slate-50 p-1 rounded-2xl border border-slate-200 w-full sm:w-auto shadow-sm">
              {(['today', 'week', 'month', 'custom'] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  className={`flex-1 sm:flex-none py-2 px-4 rounded-xl text-xs font-semibold transition-all duration-300 ${
                    period === p 
                      ? 'bg-white text-blue-600 shadow-sm border border-slate-200 scale-95' 
                      : 'text-slate-500 hover:text-slate-800 hover:bg-white'
                  }`}
                >
                  {p === 'today' ? 'Сегодня' : p === 'week' ? '7 дней' : p === 'month' ? '30 дней' : 'Интервал'}
                </button>
              ))}
            </div>

            {/* Custom Range Picker */}
            {period === 'custom' && (
              <div className="flex items-center gap-2 animate-fade-in-up w-full sm:w-auto">
                <div className="flex items-center gap-2 bg-slate-50 px-3 py-2 rounded-xl border border-slate-200 text-slate-700 flex-1 shadow-sm">
                  <Calendar size={16} className="text-slate-500" />
                  <input
                    type="date"
                    value={dateFrom}
                    onChange={(e) => setDateFrom(e.target.value)}
                    className="bg-transparent text-slate-800 focus:outline-none text-xs w-full sm:w-28"
                  />
                </div>
                <div className="flex items-center gap-2 bg-slate-50 px-3 py-2 rounded-xl border border-slate-200 text-slate-700 flex-1 shadow-sm">
                  <Calendar size={16} className="text-slate-500" />
                  <input
                    type="date"
                    value={dateTo}
                    onChange={(e) => setDateTo(e.target.value)}
                    className="bg-transparent text-slate-800 focus:outline-none text-xs w-full sm:w-28"
                  />
                </div>
              </div>
            )}
          </div>

        </div>
      </div>

      {/* Info notification about current filter */}
      <div className="flex justify-between items-center px-2">
        <p className="text-xs text-slate-500 font-medium">
          Отображаются записи за выбранный период: <span className="text-slate-800 font-bold">{operations.length} шт.</span>
        </p>
      </div>

      {/* Daily activity volume chart */}
      {stats.dates.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-3xl p-6 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-800 mb-6 flex items-center gap-2">
            <TrendUp size={18} className="text-blue-400" /> Динамика операций
          </h3>
          <div className="h-40 relative">
            <Bar data={chartData} options={chartOptions} />
          </div>
        </div>
      )}

      {/* Main Content Tabs */}
      <div className="space-y-6">
        <div className="flex bg-white p-1.5 rounded-2xl border border-slate-200 w-full sm:max-w-md mx-auto sm:mx-0 shadow-sm">
          <button
            onClick={() => setActiveTab('list')}
            className={`flex-1 py-2.5 rounded-xl text-sm font-semibold transition-all duration-300 flex items-center justify-center gap-2 ${
              activeTab === 'list' 
                ? 'bg-blue-50 text-blue-700 shadow-sm border border-slate-200' 
                : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <ListBullets size={18} /> Список
          </button>
          <button
            onClick={() => setActiveTab('summary')}
            className={`flex-1 py-2.5 rounded-xl text-sm font-semibold transition-all duration-300 flex items-center justify-center gap-2 ${
              activeTab === 'summary' 
                ? 'bg-blue-50 text-blue-700 shadow-sm border border-slate-200' 
                : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <ChartPieSlice size={18} /> Сводка
          </button>
        </div>

        {loading ? (
          <div className="flex flex-col items-center justify-center py-24 space-y-4">
            <div className="w-10 h-10 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin" />
            <p className="text-slate-500 text-sm animate-pulse">Синхронизация данных...</p>
          </div>
        ) : activeTab === 'list' ? (
          /* Detailed Operations List */
          operations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 bg-slate-50 rounded-3xl border border-dashed border-slate-200">
              <Funnel size={48} className="text-slate-300 mb-4" />
              <p className="text-slate-500 text-sm font-medium">Нет операций за выбранный период.</p>
              <p className="text-slate-400 text-xs mt-1">Попробуйте изменить фильтры или очистить поиск.</p>
            </div>
          ) : (
            <div className="grid gap-3 animate-fade-in-up">
              {operations.map((op, idx) => {
                const isTake = op.quantityChange < 0;
                const absQty = Math.abs(op.quantityChange);
                const { date, time } = formatDateTime(op.timestamp);
                
                return (
                  <div 
                    key={op.id || idx} 
                    className="group relative bg-white hover:bg-slate-50 transition-all duration-300 rounded-2xl p-4 md:p-5 border border-slate-200 hover:border-slate-300 shadow-sm hover:shadow-md flex flex-col md:flex-row items-start md:items-center gap-4 md:gap-6"
                  >
                    {/* Operation Icon Indicator */}
                    <div className={`flex-shrink-0 w-12 h-12 rounded-2xl flex items-center justify-center ${
                      isTake ? 'bg-rose-50 text-rose-500 border border-rose-100' : 'bg-emerald-50 text-emerald-500 border border-emerald-100'
                    }`}>
                      {isTake ? <ArrowUpRight size={24} weight="bold" /> : <ArrowDownLeft size={24} weight="bold" />}
                    </div>

                    {/* Main Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className="text-base font-bold text-slate-800 truncate">{op.itemName}</h4>
                        <span className={`px-2.5 py-0.5 rounded-lg text-xs font-bold ${
                          isTake ? 'bg-rose-500/20 text-rose-300' : 'bg-emerald-500/20 text-emerald-300'
                        }`}>
                          {isTake ? `Выдача` : `Возврат`} {absQty}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                        <div className="flex items-center gap-1.5 text-slate-500">
                          <User size={14} />
                          <span className="truncate max-w-[150px] md:max-w-xs text-slate-700">
                            {op.issuerName || op.userName || 'Неизвестно'}
                          </span>
                        </div>
                        {op.recipientName && (
                          <div className="flex items-center gap-1.5 text-slate-500 border-l border-slate-200 pl-4">
                            <span className="text-xs">Для:</span>
                            <span className="truncate max-w-[150px] md:max-w-xs font-medium text-slate-700">
                              {op.recipientName}
                            </span>
                          </div>
                        )}
                      </div>
                      {op.notes && (
                        <p className="mt-2 text-xs text-slate-500 line-clamp-2">
                          Примечание: {op.notes}
                        </p>
                      )}
                    </div>

                    {/* Timestamp */}
                    <div className="flex-shrink-0 text-right md:w-28">
                      <div className="flex items-center justify-end gap-1.5 text-slate-700 font-medium">
                        <Clock size={14} className="text-slate-500" />
                        {time}
                      </div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        {date}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )
        ) : (
          /* Balance Report Summary */
          summaryData.totals.length === 0 ? (
             <div className="flex flex-col items-center justify-center py-20 bg-slate-50 rounded-3xl border border-dashed border-slate-200">
              <ChartPieSlice size={48} className="text-slate-300 mb-4" />
              <p className="text-slate-500 text-sm font-medium">Нет данных для сводки.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 animate-fade-in-up">
              {/* Items Summary Column */}
              <div className="lg:col-span-7 bg-white border border-slate-200 rounded-3xl p-6 lg:p-8 shadow-sm">
                <h3 className="text-lg font-bold text-slate-800 mb-6 flex items-center gap-3">
                  <div className="w-8 h-8 rounded-xl bg-blue-50 flex items-center justify-center">
                    <ListBullets size={18} className="text-blue-600" />
                  </div>
                  Сводка по товарам
                </h3>
                <div className="space-y-3">
                  {summaryData.totals.map((tot: any, idx: number) => (
                    <div key={idx} className="group flex justify-between items-center p-4 bg-slate-50 hover:bg-slate-100 rounded-2xl border border-slate-200 transition-colors">
                      <span className="font-semibold text-slate-800">{tot.itemName}</span>
                      <span className="font-mono text-base font-bold text-slate-700 bg-white px-3 py-1 rounded-xl shadow-sm">
                        {tot.totalQuantity} <span className="text-xs font-normal text-slate-500 ml-1">оп.</span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Employees Summary Column */}
              <div className="lg:col-span-5 bg-white border border-slate-200 rounded-3xl p-6 lg:p-8 shadow-sm">
                <h3 className="text-lg font-bold text-slate-800 mb-6 flex items-center gap-3">
                  <div className="w-8 h-8 rounded-xl bg-purple-50 flex items-center justify-center">
                    <User size={18} className="text-purple-600" />
                  </div>
                  Нагрузка
                </h3>
                <div className="space-y-6">
                  {summaryData.perEmployee.map((emp: any, idx: number) => {
                    const totalQty = emp.items.reduce((acc: number, i: any) => acc + Math.abs(i.totalQuantity), 0);
                    return (
                      <div key={idx} className="space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-slate-800">{emp.userName}</span>
                          <span className="text-xs font-bold bg-slate-100 px-2 py-1 rounded-lg text-slate-600">
                            {totalQty} оп.
                          </span>
                        </div>
                        <div className="space-y-2 pl-4 border-l-2 border-slate-200">
                          {emp.items.slice(0, 3).map((i: any, subIdx: number) => (
                            <div key={subIdx} className="flex justify-between text-xs text-slate-600">
                              <span className="truncate pr-2">{i.itemName}</span>
                              <span className="font-mono text-slate-500">
                                {i.totalQuantity}
                              </span>
                            </div>
                          ))}
                          {emp.items.length > 3 && (
                            <div className="text-xs text-slate-600 font-medium italic">
                              + еще {emp.items.length - 3} тов.
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )
        )}
      </div>
    </div>
  );
};
