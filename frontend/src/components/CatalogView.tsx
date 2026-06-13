import React, { useState, useEffect, useRef } from 'react';
import { db, performOptimisticStockOperation, triggerSync, registerSyncStateListener } from '../db';
import { api, type WarehouseItem, type AuthState, type Employee, type ForecastItem } from '../api';
import { QRCodeSVG } from 'qrcode.react';
import { 
  MagnifyingGlass, 
  GridFour, 
  List, 
  Plus, 
  Warning, 
  Minus,
  CheckCircle,
  PencilSimple,
  Trash,
  X,
  ArrowsLeftRight,
  ArrowCircleUp,
  ArrowCircleDown,
  Camera,
  QrCode,
  Printer
} from '@phosphor-icons/react';
import { BarcodeScanner } from './BarcodeScanner';
import { ImageUploader } from './ImageUploader';

interface CatalogViewProps {
  currentUserState: AuthState;
}

/** Remove non-serializable properties from Dexie objects before React state */
function sanitizeItems(raw: any[]): WarehouseItem[] {
  return JSON.parse(JSON.stringify(raw));
}

export const CatalogView: React.FC<CatalogViewProps> = ({ currentUserState }) => {
  const [items, setItems] = useState<WarehouseItem[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  
  // Filtering & UI parameters
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [showLowStockOnly, setShowLowStockOnly] = useState(false);
  const [showForecastOnly, setShowForecastOnly] = useState(false);
  const [forecastData, setForecastData] = useState<ForecastItem[]>([]);
  const [isGridView, setIsGridView] = useState(true);

  // Modal parameter states
  const [activeItem, setActiveItem] = useState<WarehouseItem | null>(null);
  const [actionTab, setActionTab] = useState<'take' | 'add' | 'return'>('take');
  const [actionQuantity, setActionQuantity] = useState(1);
  const [isExtendedTake, setIsExtendedTake] = useState(false);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState('');
  const [actionNotes, setActionNotes] = useState('');
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showScanner, setShowScanner] = useState(false);
  const [qrItem, setQrItem] = useState<WarehouseItem | null>(null);
  const qrPrintRef = useRef<HTMLDivElement>(null);

  // Edit / Create Modals
  const [showEditModal, setShowEditModal] = useState(false);
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [editForm, setEditForm] = useState<{
    fullName: string;
    shortName: string;
    sku: string;
    description: string;
    category: string;
    unit: string;
    stockCount: number;
    lowStockThreshold: number;
    imageUrl: string;
  }>({
    fullName: '',
    shortName: '',
    sku: '',
    description: '',
    category: 'Общее',
    unit: 'шт.',
    stockCount: 0,
    lowStockThreshold: 10,
    imageUrl: '',
  });

  const loadCatalog = async () => {
    setLoading(true);
    try {
      // 1. Fetch from local Dexie IndexedDB (0ms delay)
      let localItems = await db.items.toArray();
      setItems(sanitizeItems(localItems));

      // 2. Fetch fresh catalog updates and employees from server if online
      if (navigator.onLine) {
        // Run full sync to get delta updates
        await triggerSync();
        localItems = await db.items.toArray();
        setItems(sanitizeItems(localItems));

        // Fetch employees
        const empList = await api.employees.list();
        setEmployees(empList);
      }
    } catch (err) {
      console.error('Failed to load parts catalog:', err);
    } finally {
      setLoading(false);
    }
  };

  // Handle URL changes for filtering
  useEffect(() => {
    const handleUrlChange = () => {
      const params = new URLSearchParams(window.location.search);
      const searchParam = params.get('search');
      const categoryParam = params.get('category');
      const lowStockParam = params.get('lowStock');
      const forecastParam = params.get('forecast');
      
      setSearch(searchParam || '');
      setSelectedCategory(categoryParam || null);
      setShowLowStockOnly(lowStockParam === 'true');
      if (forecastParam === 'true') {
        setShowForecastOnly(true);
        api.dashboard.getForecast(30).then(setForecastData).catch(() => {});
      }
    };

    handleUrlChange();
    window.addEventListener('popstate', handleUrlChange);
    return () => window.removeEventListener('popstate', handleUrlChange);
  }, []);

  // Handle data loading and sync
  useEffect(() => {
    loadCatalog();

    // Subscribe to background sync status changes to reload items when sync completes
    const unsubscribeSync = registerSyncStateListener((isSync) => {
      if (!isSync) {
        db.items.toArray().then(raw => setItems(sanitizeItems(raw))).catch(console.error);
      }
    });

    return () => {
      unsubscribeSync();
    };
  }, []);

  const handleScanSuccess = (decodedText: string) => {
    let skuTarget = decodedText.trim().toLowerCase();
    
    // Если отсканирован URL, извлекаем id/sku/code
    if (skuTarget.startsWith('http://') || skuTarget.startsWith('https://')) {
      try {
        const urlObj = new URL(decodedText.trim());
        const idParam = urlObj.searchParams.get('id');
        const skuParam = urlObj.searchParams.get('sku');
        const codeParam = urlObj.searchParams.get('code');
        skuTarget = (idParam || skuParam || codeParam || skuTarget).toLowerCase();
      } catch (e) {
        console.warn('Failed to parse URL in scanner:', e);
      }
    }

    const matched = items.find(item => 
      (item.sku && item.sku.trim().toLowerCase() === skuTarget) ||
      (item.id && item.id.trim().toLowerCase() === skuTarget)
    );
    
    if (matched) {
      setShowScanner(false);
      handleOpenActionModal(matched, 'take');
    } else {
      setErrorMessage(`Деталь с кодом "${decodedText}" не найдена в базе данных`);
      setShowScanner(false);
      setTimeout(() => {
        setErrorMessage(null);
      }, 4000);
    }
  };

  // Compute unique categories from current items
  const categories = Array.from(new Set(items.map((i) => i.category || 'Общее')));

  // Local filtering logic (Runs instantly in memory)
  const filteredItems = items.filter((item) => {
    const matchesSearch = 
      item.shortName.toLowerCase().includes(search.toLowerCase()) ||
      item.fullName.toLowerCase().includes(search.toLowerCase()) ||
      (item.sku && item.sku.toLowerCase().includes(search.toLowerCase()));

    const matchesCategory = selectedCategory ? item.category === selectedCategory : true;
    const matchesLowStock = showLowStockOnly ? item.stockCount < item.lowStockThreshold : true;
    const matchesForecast = showForecastOnly
      ? forecastData.some(f => f.itemId === item.id && f.daysRemaining !== null && f.daysRemaining < 7)
      : true;

    return matchesSearch && matchesCategory && matchesLowStock && matchesForecast;
  });

  // Action Handlers
  const handleOpenActionModal = (item: WarehouseItem, tab: 'take' | 'add' | 'return' = 'take') => {
    setActiveItem(item);
    setActionTab(tab);
    setActionQuantity(1);
    setIsExtendedTake(false);
    setSelectedEmployeeId(employees[0]?.id || '');
    setActionNotes('');
    setSuccessMessage(null);
    setErrorMessage(null);
  };

  const handleStockActionSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeItem) return;

    const qty = Number(actionQuantity);
    if (isNaN(qty) || qty <= 0) {
      setErrorMessage('Количество должно быть больше нуля');
      return;
    }

    const currentUserName = currentUserState.user_name || 'Администратор';
    const currentUserId = currentUserState.user_id || 'admin';
    const emp = employees.find(e => e.id === selectedEmployeeId);
    const recipientName = emp ? emp.name : '';
    const recipientId = emp ? emp.id : '';

    let res;
    if (actionTab === 'take') {
      if (isExtendedTake) {
        if (!selectedEmployeeId) {
          setErrorMessage('Выберите сотрудника-получателя');
          return;
        }
        res = await performOptimisticStockOperation(
          'TAKE_EXTENDED',
          activeItem.id,
          qty,
          currentUserName,
          currentUserId,
          recipientName,
          recipientId,
          actionNotes
        );
      } else {
        res = await performOptimisticStockOperation(
          'TAKE',
          activeItem.id,
          qty,
          currentUserName,
          currentUserId
        );
      }
    } else if (actionTab === 'add') {
      res = await performOptimisticStockOperation(
        'ADD',
        activeItem.id,
        qty,
        currentUserName,
        currentUserId
      );
    } else {
      // Return action
      if (!selectedEmployeeId) {
        setErrorMessage('Выберите сотрудника, возвращающего товар');
        return;
      }
      res = await performOptimisticStockOperation(
        'RETURN',
        activeItem.id,
        qty,
        currentUserName,
        currentUserId,
        recipientName,
        recipientId,
        actionNotes
      );
    }

    if (res.success) {
      setSuccessMessage(res.message);
      // Fast local update for visual consistency
      setItems(prev => prev.map(item => {
        if (item.id === activeItem.id) {
          const delta = actionTab === 'take' ? -qty : qty;
          return { ...item, stockCount: item.stockCount + delta };
        }
        return item;
      }));
      
      setTimeout(() => {
        setActiveItem(null);
        setSuccessMessage(null);
      }, 1200);
    } else {
      setErrorMessage(res.message);
    }
  };

  // Edit or Create Part Modal handlers
  const handleOpenEditModal = (item: WarehouseItem | null) => {
    setErrorMessage(null);
    setSuccessMessage(null);
    if (item) {
      setIsCreatingNew(false);
      setEditForm({
        fullName: item.fullName,
        shortName: item.shortName,
        sku: item.sku || '',
        description: item.description || '',
        category: item.category,
        unit: item.unit,
        stockCount: item.stockCount,
        lowStockThreshold: item.lowStockThreshold,
        imageUrl: item.imageUrl || '',
      });
      setActiveItem(item);
    } else {
      setIsCreatingNew(true);
      setEditForm({
        fullName: '',
        shortName: '',
        sku: '',
        description: '',
        category: 'Общее',
        unit: 'шт.',
        stockCount: 0,
        lowStockThreshold: 10,
        imageUrl: '',
      });
      setActiveItem(null);
    }
    setShowEditModal(true);
  };

  const handleSaveItem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editForm.shortName || !editForm.fullName) {
      setErrorMessage('Пожалуйста заполните обязательные названия деталей');
      return;
    }

    const payload = {
      fullName: editForm.fullName,
      shortName: editForm.shortName,
      sku: editForm.sku || null,
      description: editForm.description || null,
      category: editForm.category,
      unit: editForm.unit,
      stockCount: Number(editForm.stockCount),
      lowStockThreshold: Number(editForm.lowStockThreshold),
      imageUrl: editForm.imageUrl || null,
    };

    try {
      if (isCreatingNew) {
        const res = await api.items.create(payload, currentUserState.role);
        if (res.success) {
          // Add to local DB directly
          await db.items.put({
            id: res.id,
            ...payload,
            updatedAt: new Date().toISOString(),
          });
          setSuccessMessage('Деталь успешно создана');
        }
      } else if (activeItem) {
        const res = await api.items.update(activeItem.id, payload, currentUserState.role);
        if (res.success) {
          // Update in local DB
          await db.items.update(activeItem.id, {
            ...payload,
            updatedAt: new Date().toISOString(),
          });
          setSuccessMessage('Данные детали успешно обновлены');
        }
      }

      setItems(sanitizeItems(await db.items.toArray()));
      setTimeout(() => {
        setShowEditModal(false);
        setActiveItem(null);
        setSuccessMessage(null);
      }, 1000);
    } catch (err: any) {
      console.error(err);
      setErrorMessage(err.response?.data?.detail || 'Не удалось сохранить деталь');
    }
  };

  const handleDeleteItem = async (id: string) => {
    if (!window.confirm('Вы действительно хотите удалить эту деталь?')) return;
    try {
      const res = await api.items.delete(id, currentUserState.role);
      if (res.success) {
        await db.items.delete(id);
        setItems(sanitizeItems(await db.items.toArray()));
        setShowEditModal(false);
        setActiveItem(null);
      }
    } catch (err: any) {
      console.error(err);
      alert(err.response?.data?.detail || 'Ошибка при удалении');
    }
  };

  const isManager = currentUserState.role === 'admin' || currentUserState.role === 'inventory_manager';

  const handlePrintQR = () => {
    const printWindow = window.open('', '_blank', 'width=400,height=500');
    if (!printWindow || !qrItem) return;
    const svgEl = qrPrintRef.current?.querySelector('svg');
    const svgStr = svgEl ? svgEl.outerHTML : '';
    printWindow.document.write(`
      <!DOCTYPE html><html><head><title>QR — ${qrItem.shortName}</title>
      <style>
        body { margin: 0; display: flex; flex-direction: column; align-items: center;
               justify-content: center; min-height: 100vh; font-family: sans-serif; }
        .label { text-align: center; margin-top: 12px; }
        .name { font-size: 16px; font-weight: bold; }
        .sku  { font-size: 12px; color: #555; margin-top: 4px; }
        .stock { font-size: 11px; color: #888; margin-top: 2px; }
        svg { width: 180px; height: 180px; }
        @media print { @page { margin: 0; } }
      </style></head><body>
      ${svgStr}
      <div class="label">
        <div class="name">${qrItem.shortName}</div>
        <div class="sku">SKU: ${qrItem.sku || qrItem.id}</div>
        <div class="stock">Остаток: ${qrItem.stockCount} ${qrItem.unit}</div>
      </div>
      <script>window.onload = () => { window.print(); window.close(); }<\/script>
      </body></html>`);
    printWindow.document.close();
  };

  return (
    <div className="flex flex-col lg:flex-row gap-8 items-start animate-fade-in">
      {/* Categories Sidebar (Left column) */}
      <div className="w-full lg:w-64 shrink-0 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-6">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Категории</h3>
          {selectedCategory && (
            <button
              onClick={() => setSelectedCategory(null)}
              className="text-xs text-blue-600 hover:text-blue-500 font-medium cursor-pointer"
            >
              Сбросить
            </button>
          )}
        </div>

        <div className="space-y-1.5 max-h-[350px] overflow-y-auto pr-1">
          <button
            onClick={() => setSelectedCategory(null)}
            className={`w-full text-left px-3 py-2 rounded-xl text-sm font-medium transition-all ${
              selectedCategory === null
                ? 'bg-blue-50 text-blue-700 shadow-sm'
                : 'text-slate-600 hover:bg-slate-50'
            }`}
          >
            Все категории ({items.length})
          </button>
          
          {categories.map((cat) => {
            const count = items.filter((i) => i.category === cat).length;
            return (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`w-full text-left px-3 py-2 rounded-xl text-sm font-medium transition-all flex justify-between items-center ${
                  selectedCategory === cat
                    ? 'bg-blue-50 text-blue-700 shadow-sm'
                    : 'text-slate-600 hover:bg-slate-50'
                }`}
              >
                <span>{cat}</span>
                <span className={`text-xxs px-1.5 py-0.5 rounded-full ${selectedCategory === cat ? 'bg-blue-200 text-blue-800' : 'bg-slate-100 text-slate-500'}`}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        <hr className="border-slate-200" />

        {/* Quick Filter */}
        <div className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Фильтры состояния</h4>
          <label className="flex items-center gap-2.5 text-sm text-slate-700 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showLowStockOnly}
              onChange={(e) => setShowLowStockOnly(e.target.checked)}
              className="w-4 h-4 rounded bg-white border-slate-300 text-blue-600 focus:ring-0 focus:ring-offset-0"
            />
            <span>Критические остатки</span>
          </label>
          <label className="flex items-center gap-2.5 text-sm text-slate-700 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showForecastOnly}
              onChange={(e) => {
                setShowForecastOnly(e.target.checked);
                if (e.target.checked && forecastData.length === 0) {
                  api.dashboard.getForecast(30).then(setForecastData).catch(() => {});
                }
              }}
              className="w-4 h-4 rounded bg-white border-slate-300 text-blue-600 focus:ring-0 focus:ring-offset-0"
            />
            <span>Заканчиваются ({'<'} 7 дней)</span>
          </label>
        </div>
      </div>

      {/* Main Grid View Area (Right column) */}
      <div className="flex-1 space-y-6 w-full">
        {/* General Alert Messages when modal is closed */}
        {!activeItem && errorMessage && (
          <div className="p-4 bg-rose-500/10 border border-rose-500/20 text-rose-300 rounded-2xl text-sm flex items-center justify-between gap-3 animate-fade-in shadow-lg">
            <span>{errorMessage}</span>
            <button 
              onClick={() => setErrorMessage(null)}
              className="p-1 hover:bg-rose-500/20 text-rose-400 hover:text-rose-300 rounded-lg cursor-pointer transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        )}

        {/* Search, Layout options and CRUD buttons */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="relative w-full sm:max-w-md flex items-center">
            <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-slate-400">
              <MagnifyingGlass size={18} />
            </span>
            <input
              type="text"
              placeholder="Поиск по названию или SKU..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-12 py-2.5 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 placeholder-slate-400 focus:outline-none transition-all text-sm shadow-sm"
            />
            <button
              onClick={() => {
                setErrorMessage(null);
                setShowScanner(true);
              }}
              className="absolute right-2 p-1.5 bg-blue-50 hover:bg-blue-100 text-blue-600 rounded-lg cursor-pointer transition-colors"
              title="Сканировать штрих-код"
            >
              <Camera size={18} />
            </button>
          </div>

          <div className="flex items-center gap-3 w-full sm:w-auto justify-end">
            {/* View Toggles */}
            <div className="flex bg-white p-1 rounded-xl border border-slate-200 shadow-sm">
              <button
                onClick={() => setIsGridView(true)}
                className={`p-1.5 rounded-lg transition-colors cursor-pointer ${isGridView ? 'bg-slate-100 text-blue-600' : 'text-slate-400 hover:text-slate-600'}`}
              >
                <GridFour size={18} />
              </button>
              <button
                onClick={() => setIsGridView(false)}
                className={`p-1.5 rounded-lg transition-colors cursor-pointer ${!isGridView ? 'bg-slate-100 text-blue-600' : 'text-slate-400 hover:text-slate-600'}`}
              >
                <List size={18} />
              </button>
            </div>

            {/* Create Part Button */}
            {isManager && (
              <button
                onClick={() => handleOpenEditModal(null)}
                className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white font-medium py-2 px-4 rounded-xl text-sm transition-all duration-150 cursor-pointer shadow-lg shadow-blue-500/10"
              >
                <Plus size={16} weight="bold" />
                Добавить деталь
              </button>
            )}
          </div>
        </div>

        {/* Catalog Items Renderer */}
        {loading && items.length === 0 ? (
          <div className="text-center py-20 text-slate-500 text-sm">
            Загрузка каталога запчастей...
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-20 text-slate-500 text-sm border border-dashed border-slate-200 rounded-2xl bg-slate-50">
            Детали не найдены
          </div>
        ) : isGridView ? (
          /* Grid View Layout */
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredItems.map((item) => {
              const isLowStock = item.stockCount < item.lowStockThreshold;
              return (
                <div 
                  key={item.id} 
                  className={`bg-white border rounded-2xl overflow-hidden hover:-translate-y-1 transition-all duration-200 flex flex-col relative group ${
                    isLowStock ? 'border-amber-200 hover:border-amber-400 shadow-sm hover:shadow-md' : 'border-slate-200 hover:border-slate-300 shadow-sm hover:shadow-md'
                  }`}
                >
                  {/* Thumbnail / Info image */}
                  <div className="h-40 bg-slate-50 flex items-center justify-center relative overflow-hidden border-b border-slate-100">
                    {item.imageUrl ? (
                      <img src={item.imageUrl} alt={item.shortName} className="object-cover w-full h-full group-hover:scale-105 transition-transform duration-300" />
                    ) : (
                      <div className="text-slate-400 text-sm font-semibold uppercase tracking-wider bg-slate-100 w-16 h-16 rounded-2xl flex items-center justify-center border border-slate-200">
                        {item.shortName.substring(0, 2)}
                      </div>
                    )}

                    {isLowStock && (
                      <span className="absolute top-3 right-3 bg-amber-500/10 text-amber-400 border border-amber-500/20 text-xxs font-bold px-2 py-0.5 rounded-full flex items-center gap-1 shadow-sm">
                        <Warning size={12} /> мало
                      </span>
                    )}
                  </div>

                  <div className="p-5 flex-1 flex flex-col justify-between">
                    <div>
                      <span className="text-xxs text-blue-500 font-semibold uppercase tracking-wider">{item.category}</span>
                      <h4 className="text-base font-bold text-slate-800 mt-1 leading-tight line-clamp-1">{item.shortName}</h4>
                      <p className="text-xs text-slate-500 mt-1 line-clamp-2 leading-relaxed min-h-[2.5rem]">{item.fullName}</p>
                      
                      {item.sku && (
                        <div className="text-xs text-slate-500 font-mono mt-2 flex items-center gap-1">
                          SKU: <span className="text-slate-600">{item.sku}</span>
                        </div>
                      )}
                    </div>

                    <div className="mt-5 border-t border-slate-100 pt-4 flex items-center justify-between">
                      <div>
                        <span className="text-slate-500 text-xxs block uppercase font-bold">Остаток</span>
                        <span className={`text-xl font-bold ${isLowStock ? 'text-amber-500' : 'text-slate-800'}`}>
                          {item.stockCount} <span className="text-xs font-normal text-slate-500">{item.unit}</span>
                        </span>
                      </div>

                      {/* Item Quick Actions */}
                      <div className="flex items-center gap-2">
                        {isManager && (
                          <button
                            onClick={() => handleOpenEditModal(item)}
                            className="p-2 bg-slate-50 hover:bg-slate-100 text-slate-500 hover:text-slate-800 rounded-lg border border-slate-200 transition-colors cursor-pointer"
                            title="Редактировать"
                          >
                            <PencilSimple size={15} />
                          </button>
                        )}
                        <button
                          onClick={() => setQrItem(item)}
                          className="p-2 bg-slate-50 hover:bg-indigo-50 text-slate-500 hover:text-indigo-600 rounded-lg border border-slate-200 transition-colors cursor-pointer"
                          title="QR-код для печати"
                        >
                          <QrCode size={15} />
                        </button>
                        <button
                          onClick={() => handleOpenActionModal(item, 'take')}
                          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-blue-500/5 transition-all cursor-pointer"
                        >
                          Списать/Выдать
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          /* List View Layout */
          <div className="bg-white rounded-2xl overflow-hidden border border-slate-200 shadow-sm">
            <table className="w-full text-left text-sm border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-slate-500 text-xs font-semibold uppercase tracking-wider">
                  <th className="p-4 pl-6">Запчасть</th>
                  <th className="p-4 hidden sm:table-cell">Категория</th>
                  <th className="p-4 hidden md:table-cell">SKU</th>
                  <th className="p-4 text-center">Остаток</th>
                  <th className="p-4 pr-6 text-right">Действия</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredItems.map((item) => {
                  const isLowStock = item.stockCount < item.lowStockThreshold;
                  return (
                    <tr key={item.id} className="hover:bg-slate-50 transition-colors">
                      <td className="p-4 pl-6">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center shrink-0 border border-slate-200 overflow-hidden">
                            {item.imageUrl ? (
                              <img src={item.imageUrl} alt="" className="object-cover w-full h-full" />
                            ) : (
                              <span className="text-slate-500 text-xs font-bold uppercase">{item.shortName.substring(0, 2)}</span>
                            )}
                          </div>
                          <div>
                            <span className="font-bold text-slate-800 block leading-normal">{item.shortName}</span>
                            <span className="text-xs text-slate-500 line-clamp-1 max-w-xs">{item.fullName}</span>
                          </div>
                        </div>
                      </td>
                      <td className="p-4 hidden sm:table-cell">
                        <span className="text-xs text-slate-600 font-semibold px-2 py-0.5 bg-slate-100 rounded-md border border-slate-200">
                          {item.category}
                        </span>
                      </td>
                      <td className="p-4 hidden md:table-cell font-mono text-xs text-slate-500">
                        {item.sku || '—'}
                      </td>
                      <td className="p-4 text-center">
                        <span className={`font-bold ${isLowStock ? 'text-amber-500' : 'text-slate-800'}`}>
                          {item.stockCount} <span className="text-xs font-normal text-slate-500">{item.unit}</span>
                        </span>
                        {isLowStock && (
                          <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 ml-1.5" title="Мало на складе"></span>
                        )}
                      </td>
                      <td className="p-4 pr-6 text-right">
                        <div className="flex items-center gap-2 justify-end">
                          {isManager && (
                            <button
                              onClick={() => handleOpenEditModal(item)}
                              className="p-2 bg-slate-50 hover:bg-slate-100 text-slate-500 hover:text-slate-800 rounded-lg border border-slate-200 transition-colors cursor-pointer"
                            >
                              <PencilSimple size={14} />
                            </button>
                          )}
                          <button
                            onClick={() => setQrItem(item)}
                            className="p-2 bg-slate-50 hover:bg-indigo-50 text-slate-500 hover:text-indigo-600 rounded-lg border border-slate-200 transition-colors cursor-pointer"
                            title="QR-код"
                          >
                            <QrCode size={14} />
                          </button>
                          <button
                            onClick={() => handleOpenActionModal(item, 'take')}
                            className="px-2.5 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-lg shadow-blue-500/5 transition-all cursor-pointer"
                          >
                            Списать
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 1. Transaction Dialog Modal (Take / Add / Return) */}
      {activeItem && !showEditModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="w-full max-w-lg bg-white rounded-2xl shadow-2xl p-6 border border-slate-200 animate-fade-in max-h-[90vh] overflow-y-auto">
            {/* Modal Head */}
            <div className="flex items-start justify-between mb-5">
              <div>
                <h3 className="text-lg font-bold text-slate-800">Операция с деталью</h3>
                <p className="text-xs text-slate-500 mt-0.5">{activeItem.shortName}</p>
              </div>
              <button
                onClick={() => setActiveItem(null)}
                className="p-1 bg-slate-100 hover:bg-slate-200 text-slate-500 hover:text-slate-800 rounded-lg cursor-pointer"
              >
                <X size={20} />
              </button>
            </div>

            {successMessage && (
              <div className="mb-4 p-3.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 rounded-xl text-sm flex items-center gap-2">
                <CheckCircle size={18} />
                {successMessage}
              </div>
            )}
            {errorMessage && (
              <div className="mb-4 p-3.5 bg-rose-500/10 border border-rose-500/20 text-rose-300 rounded-xl text-sm">
                {errorMessage}
              </div>
            )}

            {/* Modal Form */}
            <form onSubmit={handleStockActionSubmit} className="space-y-5">
              {/* Tab Selector */}
              <div className="flex bg-slate-100 p-1 rounded-xl border border-slate-200">
                <button
                  type="button"
                  onClick={() => { setActionTab('take'); setErrorMessage(null); }}
                  className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
                    actionTab === 'take' ? 'bg-white text-blue-600 shadow-sm border border-slate-200' : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  <ArrowCircleDown size={14} /> Выдать / Списать
                </button>
                <button
                  type="button"
                  onClick={() => { setActionTab('add'); setErrorMessage(null); }}
                  className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
                    actionTab === 'add' ? 'bg-white text-emerald-600 shadow-sm border border-slate-200' : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  <ArrowCircleUp size={14} /> Пополнить
                </button>
                {isManager && (
                  <button
                    type="button"
                    onClick={() => { setActionTab('return'); setErrorMessage(null); }}
                    className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
                      actionTab === 'return' ? 'bg-white text-purple-600 shadow-sm border border-slate-200' : 'text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <ArrowsLeftRight size={14} /> Возврат
                  </button>
                )}
              </div>

              {/* Quantity Input */}
              <div>
                <label className="block text-slate-700 text-sm font-medium mb-1.5">
                  Количество ({activeItem.unit})
                </label>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setActionQuantity(prev => Math.max(1, prev - 1))}
                    className="p-2.5 bg-white hover:bg-slate-50 text-slate-500 hover:text-slate-800 rounded-xl border border-slate-200 shadow-sm cursor-pointer"
                  >
                    <Minus size={16} />
                  </button>
                  <input
                    type="number"
                    min="1"
                    value={actionQuantity}
                    onChange={(e) => setActionQuantity(Math.max(1, parseInt(e.target.value) || 1))}
                    className="flex-1 text-center py-2.5 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 font-bold placeholder-slate-400 focus:outline-none text-base shadow-sm"
                  />
                  <button
                    type="button"
                    onClick={() => setActionQuantity(prev => prev + 1)}
                    className="p-2.5 bg-white hover:bg-slate-50 text-slate-500 hover:text-slate-800 rounded-xl border border-slate-200 shadow-sm cursor-pointer"
                  >
                    <Plus size={16} />
                  </button>
                </div>
              </div>

              {/* Extended Take Option — only for managers */}
              {actionTab === 'take' && isManager && (
                <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 space-y-4">
                  <label className="flex items-center gap-2.5 text-sm text-slate-700 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={isExtendedTake}
                      onChange={(e) => setIsExtendedTake(e.target.checked)}
                      className="w-4 h-4 rounded bg-white border-slate-300 text-blue-600 focus:ring-0 focus:ring-offset-0"
                    />
                    <span className="font-medium">Выдать конкретному сотруднику</span>
                  </label>

                  {isExtendedTake && (
                    <div className="animate-fade-in space-y-3">
                      <div>
                        <label className="block text-slate-600 text-xs font-semibold uppercase tracking-wider mb-1.5">Сотрудник</label>
                        <select
                          value={selectedEmployeeId}
                          onChange={(e) => setSelectedEmployeeId(e.target.value)}
                          className="w-full py-2.5 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 placeholder-slate-400 focus:outline-none text-sm shadow-sm"
                        >
                          <option value="">Выберите сотрудника...</option>
                          {employees.map(emp => (
                            <option key={emp.id} value={emp.id}>{emp.name}</option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="block text-slate-600 text-xs font-semibold uppercase tracking-wider mb-1.5">Примечание / Задача</label>
                        <input
                          type="text"
                          placeholder="Например: на ремонт подъемника"
                          value={actionNotes}
                          onChange={(e) => setActionNotes(e.target.value)}
                          className="w-full py-2.5 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 placeholder-slate-400 focus:outline-none text-sm shadow-sm"
                        />
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Return Fields — only for managers */}
              {actionTab === 'return' && isManager && (
                <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 space-y-4 animate-fade-in">
                  <div>
                    <label className="block text-slate-600 text-xs font-semibold uppercase tracking-wider mb-1.5">Кто возвращает</label>
                    <select
                      value={selectedEmployeeId}
                      onChange={(e) => setSelectedEmployeeId(e.target.value)}
                      className="w-full py-2.5 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 placeholder-slate-400 focus:outline-none text-sm shadow-sm"
                    >
                      <option value="">Выберите сотрудника...</option>
                      {employees.map(emp => (
                        <option key={emp.id} value={emp.id}>{emp.name}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-slate-600 text-xs font-semibold uppercase tracking-wider mb-1.5">Причина возврата</label>
                    <input
                      type="text"
                      placeholder="Например: деталь лишняя / не подошла"
                      value={actionNotes}
                      onChange={(e) => setActionNotes(e.target.value)}
                      className="w-full py-2.5 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 placeholder-slate-400 focus:outline-none text-sm shadow-sm"
                    />
                  </div>
                </div>
              )}

              {/* Submit Buttons */}
              <div className="flex gap-4 pt-3">
                <button
                  type="button"
                  onClick={() => setActiveItem(null)}
                  className="flex-1 py-3 bg-white hover:bg-slate-50 border border-slate-200 text-slate-600 font-medium rounded-xl text-sm transition-colors duration-150 cursor-pointer text-center shadow-sm"
                >
                  Отмена
                </button>
                <button
                  type="submit"
                  className={`flex-1 py-3 text-white font-medium rounded-xl text-sm transition-all duration-150 cursor-pointer shadow-lg text-center ${
                    actionTab === 'take' 
                      ? 'bg-blue-600 hover:bg-blue-500 shadow-blue-500/10' 
                      : actionTab === 'add'
                      ? 'bg-emerald-600 hover:bg-emerald-500 shadow-emerald-500/10'
                      : 'bg-purple-600 hover:bg-purple-500 shadow-purple-500/10'
                  }`}
                >
                  Подтвердить
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 2. Admin Edit or Create Part Modal */}
      {showEditModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4 bg-slate-900/40 backdrop-blur-sm">
          <div className="w-full max-w-xl bg-white rounded-2xl shadow-2xl p-6 border border-slate-200 animate-fade-in max-h-[90vh] overflow-y-auto">
            {/* Modal Head */}
            <div className="flex items-start justify-between mb-5">
              <div>
                <h3 className="text-lg font-bold text-slate-800">
                  {isCreatingNew ? 'Создание новой детали' : 'Редактирование детали'}
                </h3>
              </div>
              <button
                onClick={() => { setShowEditModal(false); setActiveItem(null); }}
                className="p-1 bg-slate-100 hover:bg-slate-200 text-slate-500 hover:text-slate-800 rounded-lg cursor-pointer"
              >
                <X size={20} />
              </button>
            </div>

            {successMessage && (
              <div className="mb-4 p-3.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 rounded-xl text-sm">
                {successMessage}
              </div>
            )}
            {errorMessage && (
              <div className="mb-4 p-3.5 bg-rose-500/10 border border-rose-500/20 text-rose-300 rounded-xl text-sm">
                {errorMessage}
              </div>
            )}

            <form onSubmit={handleSaveItem} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-slate-700 text-xs font-semibold uppercase tracking-wider mb-1">Короткое название *</label>
                  <input
                    type="text"
                    required
                    placeholder="Например: Стяжка 200мм"
                    value={editForm.shortName}
                    onChange={(e) => setEditForm({ ...editForm, shortName: e.target.value })}
                    className="w-full py-2.5 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 text-sm focus:outline-none shadow-sm"
                  />
                </div>
                <div>
                  <label className="block text-slate-700 text-xs font-semibold uppercase tracking-wider mb-1">SKU / Артикул</label>
                  <input
                    type="text"
                    placeholder="Артикул или скан-код"
                    value={editForm.sku}
                    onChange={(e) => setEditForm({ ...editForm, sku: e.target.value })}
                    className="w-full py-2.5 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 text-sm focus:outline-none shadow-sm"
                  />
                </div>
              </div>

              <div>
                <label className="block text-slate-700 text-xs font-semibold uppercase tracking-wider mb-1">Полное описание детали *</label>
                <input
                  type="text"
                  required
                  placeholder="Например: Кабельная стяжка нейлоновая черная Rexant"
                  value={editForm.fullName}
                  onChange={(e) => setEditForm({ ...editForm, fullName: e.target.value })}
                  className="w-full py-2.5 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 text-sm focus:outline-none shadow-sm"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className="block text-slate-700 text-xs font-semibold uppercase tracking-wider mb-1">Категория</label>
                  <input
                    type="text"
                    placeholder="Общее"
                    value={editForm.category}
                    onChange={(e) => setEditForm({ ...editForm, category: e.target.value })}
                    className="w-full py-2.5 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 text-sm focus:outline-none shadow-sm"
                  />
                </div>
                <div>
                  <label className="block text-slate-700 text-xs font-semibold uppercase tracking-wider mb-1">Ед. измерения</label>
                  <input
                    type="text"
                    placeholder="шт. / м. / уп."
                    value={editForm.unit}
                    onChange={(e) => setEditForm({ ...editForm, unit: e.target.value })}
                    className="w-full py-2.5 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 text-sm focus:outline-none shadow-sm"
                  />
                </div>
                <div>
                  <label className="block text-slate-700 text-xs font-semibold uppercase tracking-wider mb-1">Порог дефицита</label>
                  <input
                    type="number"
                    placeholder="10"
                    value={editForm.lowStockThreshold}
                    onChange={(e) => setEditForm({ ...editForm, lowStockThreshold: parseInt(e.target.value) || 10 })}
                    className="w-full py-2.5 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 text-sm focus:outline-none shadow-sm"
                  />
                </div>
              </div>

              {isCreatingNew && (
                <div>
                  <label className="block text-slate-700 text-xs font-semibold uppercase tracking-wider mb-1">Начальное количество</label>
                  <input
                    type="number"
                    value={editForm.stockCount}
                    onChange={(e) => setEditForm({ ...editForm, stockCount: parseInt(e.target.value) || 0 })}
                    className="w-full py-2.5 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 text-sm focus:outline-none shadow-sm"
                  />
                </div>
              )}

              <div>
                <label className="block text-slate-700 text-xs font-semibold uppercase tracking-wider mb-1">Фото товара</label>
                <ImageUploader
                  currentUrl={editForm.imageUrl}
                  onUploaded={(url) => setEditForm({ ...editForm, imageUrl: url })}
                />
              </div>

              {/* Description */}
              <div>
                <label className="block text-slate-700 text-xs font-semibold uppercase tracking-wider mb-1">Подробное примечание</label>
                <textarea
                  placeholder="Дополнительные технические характеристики..."
                  value={editForm.description}
                  onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                  className="w-full py-2 px-3 bg-white border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 text-sm focus:outline-none h-20 resize-none shadow-sm"
                />
              </div>

              {/* Modal Buttons */}
              <div className="flex items-center justify-between pt-4 gap-4">
                {!isCreatingNew && activeItem && (
                  <button
                    type="button"
                    onClick={() => handleDeleteItem(activeItem.id)}
                    className="flex items-center gap-1 bg-rose-600/10 hover:bg-rose-600/20 text-rose-400 border border-rose-500/10 py-2.5 px-4 rounded-xl text-sm transition-colors cursor-pointer"
                  >
                    <Trash size={16} /> Удалить деталь
                  </button>
                )}

                <div className="flex gap-4 flex-1 justify-end">
                  <button
                    type="button"
                    onClick={() => { setShowEditModal(false); setActiveItem(null); }}
                    className="py-2.5 px-5 bg-white hover:bg-slate-50 border border-slate-200 text-slate-600 font-medium rounded-xl text-sm transition-colors cursor-pointer shadow-sm"
                  >
                    Отмена
                  </button>
                  <button
                    type="submit"
                    className="py-2.5 px-6 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-xl text-sm transition-all cursor-pointer shadow-lg shadow-blue-500/10"
                  >
                    Сохранить
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Barcode scanner camera overlay */}
      {showScanner && (
        <BarcodeScanner
          onScanSuccess={handleScanSuccess}
          onClose={() => setShowScanner(false)}
        />
      )}

      {/* QR Code Modal */}
      {qrItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4 bg-slate-900/50 backdrop-blur-sm">
          <div className="w-full max-w-sm bg-white rounded-3xl shadow-2xl p-8 border border-slate-200 animate-fade-in flex flex-col items-center gap-6">
            {/* Header */}
            <div className="w-full flex items-center justify-between">
              <div className="flex items-center gap-2 text-slate-700 font-bold text-base">
                <QrCode size={20} className="text-indigo-500" />
                QR-наклейка
              </div>
              <button
                onClick={() => setQrItem(null)}
                className="p-1.5 bg-slate-100 hover:bg-slate-200 text-slate-500 rounded-lg cursor-pointer transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* QR Code */}
            <div
              ref={qrPrintRef}
              className="flex flex-col items-center gap-4 p-6 bg-white border-2 border-dashed border-slate-200 rounded-2xl w-full"
            >
              <QRCodeSVG
                value={window.location.origin + "/mobile/take_part?id=" + qrItem.id}
                size={180}
                bgColor="#ffffff"
                fgColor="#1e293b"
                level="M"
                includeMargin={true}
              />
              <div className="text-center">
                <p className="text-base font-bold text-slate-800 leading-tight">{qrItem.shortName}</p>
                <p className="text-xs text-slate-500 font-mono mt-1">SKU: {qrItem.sku || qrItem.id}</p>
                <p className="text-xs text-slate-400 mt-0.5">Остаток: {qrItem.stockCount} {qrItem.unit}</p>
              </div>
            </div>

            {/* Info */}
            <p className="text-xs text-slate-400 text-center">
              QR содержит SKU товара. При сканировании телефоном — откроется карточка для списания.
            </p>

            {/* Actions */}
            <div className="flex gap-3 w-full">
              <button
                onClick={() => setQrItem(null)}
                className="flex-1 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-xl text-sm font-medium transition-colors cursor-pointer"
              >
                Закрыть
              </button>
              <button
                onClick={handlePrintQR}
                className="flex-1 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-colors cursor-pointer shadow-lg shadow-indigo-500/20"
              >
                <Printer size={16} />
                Печать
              </button>
            </div>
          </div>
        </div>
      )}

    </div>

  );
};
