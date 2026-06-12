import React, { useState, useEffect, useRef } from 'react';
import { api, type AuthState } from '../api';
import { 
  FileXls, 
  FileCsv, 
  UploadSimple, 
  DownloadSimple, 
  SpinnerGap, 
  CheckCircle, 
  Warning, 
  Terminal
} from '@phosphor-icons/react';

interface ImportExportViewProps {
  currentUserState: AuthState;
}

interface ImportStatus {
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  progress: number;
  status_text: string;
  created_count: number;
  updated_count: number;
  error_count: number;
  logs: string[];
}

export const ImportExportView: React.FC<ImportExportViewProps> = ({ currentUserState }) => {
  const isManagerOrAdmin = ['admin', 'inventory_manager'].includes(currentUserState.role || '');

  // Excel Import States
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [excelTaskId, setExcelTaskId] = useState<string | null>(null);
  const [excelStatus, setExcelStatus] = useState<ImportStatus | null>(null);
  const [excelLoading, setExcelLoading] = useState(false);
  const [excelError, setExcelError] = useState<string | null>(null);

  // CSV States
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvLoading, setCsvLoading] = useState(false);
  const [csvMessage, setCsvMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const logsEndRef = useRef<HTMLDivElement | null>(null);
  const pollIntervalRef = useRef<number | null>(null);

  // Auto scroll terminal logs
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [excelStatus?.logs]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // Poll status helper
  const pollStatus = async (taskId: string) => {
    try {
      const data = await api.items.getImportStatus(taskId) as unknown as ImportStatus;
      setExcelStatus(data);

      if (data.status === 'COMPLETED' || data.status === 'FAILED') {
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
        setExcelLoading(false);
        setExcelFile(null);
      }
    } catch (err) {
      console.error('Failed to poll excel status:', err);
    }
  };

  // Excel Import Handler
  const handleExcelImport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!excelFile) return;

    setExcelLoading(true);
    setExcelError(null);
    setExcelStatus(null);
    
    try {
      const result = await api.items.importExcel(excelFile, currentUserState.role || 'user');
      if (result.success && result.task_id) {
        setExcelTaskId(result.task_id);
        
        // Start polling immediately and every 2 seconds
        pollStatus(result.task_id);
        pollIntervalRef.current = window.setInterval(() => {
          pollStatus(result.task_id);
        }, 2000);
      } else {
        setExcelError('Ошибка при создании задачи импорта');
        setExcelLoading(false);
      }
    } catch (err: any) {
      console.error(err);
      setExcelError(err.response?.data?.detail || 'Не удалось запустить импорт Excel файла');
      setExcelLoading(false);
    }
  };

  // CSV Export Handler
  const handleCSVExport = async () => {
    try {
      const items = await api.items.list(100000); // fetch up to 100k items
      
      const headers = ['id', 'shortName', 'fullName', 'sku', 'category', 'unit', 'stockCount', 'totalStock', 'lowStockThreshold'];
      const csvRows = [headers.join(',')];
      
      for (const item of items) {
        const row = headers.map(header => {
          const val = (item as any)[header] ?? '';
          return `"${val.toString().replace(/"/g, '""')}"`;
        }).join(',');
        csvRows.push(row);
      }
      
      const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `warehouse_items_${new Date().toISOString().split('T')[0]}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export CSV:', err);
      alert('Ошибка при экспорте данных в CSV');
    }
  };

  // CSV Import Handler
  const handleCSVImport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!csvFile) return;

    setCsvLoading(true);
    setCsvMessage(null);

    const reader = new FileReader();
    reader.onload = async (event) => {
      try {
        const text = event.target?.result as string;
        if (!text) throw new Error('Файл пуст');

        const rows = text.split('\n');
        if (rows.length < 2) throw new Error('В файле нет строк данных');

        const headers = rows[0].split(',').map(h => h.replace(/"/g, '').trim());
        let successCount = 0;
        let errorCount = 0;

        for (let i = 1; i < rows.length; i++) {
          if (!rows[i].trim()) continue;
          
          const values = rows[i].split(',').map(v => v.replace(/"/g, '').trim());
          const item: any = {};
          headers.forEach((h, idx) => {
            item[h] = values[idx];
          });
          
          if (item.shortName && item.fullName) {
            try {
              await api.items.create({
                fullName: item.fullName,
                shortName: item.shortName,
                sku: item.sku || null,
                category: item.category || 'Общее',
                unit: item.unit || 'шт.',
                totalStock: parseInt(item.totalStock) || parseInt(item.stockCount) || 0,
                stockCount: parseInt(item.stockCount) || parseInt(item.totalStock) || 0,
                lowStockThreshold: parseInt(item.lowStockThreshold) || 10,
                imageUrl: item.imageUrl || null,
                description: item.description || ''
              }, currentUserState.role || 'user');
              successCount++;
            } catch (err) {
              console.error('Failed to import CSV row:', item, err);
              errorCount++;
            }
          } else {
            errorCount++;
          }
        }

        setCsvMessage({
          text: `Импорт CSV успешно завершен: добавлено деталей: ${successCount}, ошибок: ${errorCount}`,
          type: 'success'
        });
        setCsvFile(null);
      } catch (err: any) {
        console.error(err);
        setCsvMessage({
          text: err.message || 'Ошибка парсинга CSV файла',
          type: 'error'
        });
      } finally {
        setCsvLoading(false);
      }
    };

    reader.onerror = () => {
      setCsvMessage({ text: 'Ошибка чтения файла', type: 'error' });
      setCsvLoading(false);
    };

    reader.readAsText(csvFile, 'UTF-8');
  };

  return (
    <div className="space-y-8 animate-fade-in pb-10">
      {/* Title */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-slate-800 font-sans">Импорт и Экспорт</h1>
        <p className="text-slate-500 text-sm mt-1">
          Загрузка спецификаций из Excel спецификаций и обмен данными в формате CSV.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        
        {/* 1. Excel BOM Import Card */}
        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm flex flex-col justify-between hover:shadow-md transition-all duration-200">
          <div>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center text-emerald-600 border border-emerald-200">
                <FileXls size={22} />
              </div>
              <div>
                <h2 className="text-lg font-bold text-slate-800">Импорт спецификации Excel (BOM)</h2>
                <p className="text-xs text-slate-600">Автоматический перевод названий, скачивание картинок и сохранение в базу данных</p>
              </div>
            </div>

            {!isManagerOrAdmin ? (
              <div className="bg-amber-50 border border-amber-200 text-amber-700 p-4 rounded-xl flex items-start gap-3 my-6">
                <Warning size={20} className="shrink-0 mt-0.5" />
                <div className="text-xs">
                  <strong className="block font-semibold mb-1">Доступ ограничен</strong>
                  Импорт спецификаций Excel доступен только для Администраторов и Менеджеров склада. Вы можете просматривать данные и использовать CSV экспорт.
                </div>
              </div>
            ) : (
              <form onSubmit={handleExcelImport} className="space-y-5 my-6">
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Выберите Excel файл (.xlsx)</label>
                  <div className="relative border-2 border-dashed border-slate-300 hover:border-slate-400 transition-colors rounded-xl p-6 text-center cursor-pointer flex flex-col items-center justify-center bg-slate-50">
                    <input 
                      type="file" 
                      accept=".xlsx"
                      onChange={(e) => setExcelFile(e.target.files?.[0] || null)}
                      className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                      disabled={excelLoading}
                    />
                    <UploadSimple size={32} className="text-slate-400 mb-2" />
                    <span className="text-sm font-medium text-slate-700">
                      {excelFile ? excelFile.name : 'Выберите файл или перетащите его сюда'}
                    </span>
                    <span className="text-xxs text-slate-400 mt-1">Поддерживается формат Microsoft Excel (.xlsx)</span>
                  </div>
                </div>

                {excelError && (
                  <div className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-xl flex items-center gap-2 text-xs">
                    <Warning size={16} />
                    <span>{excelError}</span>
                  </div>
                )}

                <button
                  type="submit"
                  disabled={!excelFile || excelLoading}
                  className={`w-full py-3 px-4 rounded-xl text-sm font-bold flex items-center justify-center gap-2 border transition-all cursor-pointer ${
                    excelFile && !excelLoading
                      ? 'bg-emerald-600 hover:bg-emerald-500 border-emerald-500 text-white shadow-lg shadow-emerald-500/20'
                      : 'bg-slate-100 border-slate-200 text-slate-400 cursor-not-allowed'
                  }`}
                >
                  {excelLoading ? (
                    <>
                      <SpinnerGap size={18} className="animate-spin" />
                      Выполняется импорт...
                    </>
                  ) : (
                    <>
                      <UploadSimple size={18} />
                      Импортировать Excel спецификацию
                    </>
                  )}
                </button>
              </form>
            )}
          </div>

          {/* Excel Live Logs Console */}
          {excelStatus && (
            <div className="mt-4 pt-6 border-t border-slate-200 space-y-4">
              <div>
                <div className="flex justify-between items-center text-xs font-semibold text-slate-500 mb-1.5">
                  <span>Статус задачи: <strong className="text-slate-800">{excelStatus.status_text}</strong></span>
                  <span className="text-emerald-600">{excelStatus.progress}%</span>
                </div>
                
                {/* Progress bar */}
                <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden border border-slate-200">
                  <div 
                    className="h-full bg-emerald-500 transition-all duration-300" 
                    style={{ width: `${excelStatus.progress}%` }}
                  ></div>
                </div>
              </div>

              {/* Counters */}
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-slate-50 border border-slate-200 p-2.5 rounded-xl text-center shadow-sm">
                  <div className="text-xxs font-bold uppercase tracking-wider text-slate-400">Создано</div>
                  <div className="text-lg font-bold text-emerald-600 mt-0.5">{excelStatus.created_count}</div>
                </div>
                <div className="bg-slate-50 border border-slate-200 p-2.5 rounded-xl text-center shadow-sm">
                  <div className="text-xxs font-bold uppercase tracking-wider text-slate-400">Обновлено</div>
                  <div className="text-lg font-bold text-blue-600 mt-0.5">{excelStatus.updated_count}</div>
                </div>
                <div className="bg-slate-50 border border-slate-200 p-2.5 rounded-xl text-center shadow-sm">
                  <div className="text-xxs font-bold uppercase tracking-wider text-slate-400">Ошибок</div>
                  <div className="text-lg font-bold text-rose-600 mt-0.5">{excelStatus.error_count}</div>
                </div>
              </div>

              {/* Terminal Logs Box */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs font-semibold text-slate-600">
                  <div className="flex items-center gap-1.5">
                    <Terminal size={16} className="text-slate-400" />
                    <span>Журнал консоли</span>
                  </div>
                  {excelTaskId && <span className="font-mono text-slate-500 text-xxs">ID: {excelTaskId}</span>}
                </div>
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 h-44 overflow-y-auto font-mono text-xxs leading-relaxed text-slate-300 whitespace-pre-wrap">
                  {excelStatus.logs && excelStatus.logs.length > 0 ? (
                    excelStatus.logs.map((log, idx) => (
                      <div key={idx} className="border-b border-slate-800 py-0.5">
                        {log}
                      </div>
                    ))
                  ) : (
                    <div className="text-slate-600 italic">Инициализация логов...</div>
                  )}
                  <div ref={logsEndRef} />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 2. CSV Import / Export Card */}
        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm flex flex-col justify-between hover:shadow-md transition-all duration-200">
          <div className="space-y-6">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center text-blue-600 border border-blue-200">
                <FileCsv size={22} />
              </div>
              <div>
                <h2 className="text-lg font-bold text-slate-800">Импорт и Экспорт CSV</h2>
                <p className="text-xs text-slate-600">Обмен каталогом склада в легком текстовом формате CSV</p>
              </div>
            </div>

            {/* Export Section */}
            <div className="bg-slate-50 border border-slate-200 p-4 rounded-xl space-y-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Экспорт данных</h3>
              <p className="text-xs text-slate-600">
                Скачать весь текущий список деталей и остатков в виде `.csv` файла для редактирования в Excel/Таблицах.
              </p>
              <button
                onClick={handleCSVExport}
                className="w-full py-2.5 px-4 rounded-xl text-xs font-bold flex items-center justify-center gap-2 border border-slate-300 bg-white hover:bg-slate-100 text-slate-700 transition-colors cursor-pointer shadow-sm"
              >
                <DownloadSimple size={16} />
                Выгрузить каталог в CSV
              </button>
            </div>

            {/* Import Section */}
            <div className="bg-slate-50 border border-slate-200 p-4 rounded-xl space-y-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Импорт данных</h3>
              <p className="text-xs text-slate-600">
                Загрузить каталог деталей из существующего `.csv` файла. Файл должен иметь заголовки: `shortName, fullName, category, unit, stockCount`.
              </p>
              
              {!isManagerOrAdmin ? (
                <div className="text-xxs text-amber-600 font-medium">
                  * Импорт CSV доступен только Администраторам и Менеджерам склада.
                </div>
              ) : (
                <form onSubmit={handleCSVImport} className="space-y-3">
                  <div className="relative border border-dashed border-slate-300 hover:border-slate-400 transition-colors rounded-xl p-4 text-center cursor-pointer bg-white">
                    <input 
                      type="file" 
                      accept=".csv"
                      onChange={(e) => setCsvFile(e.target.files?.[0] || null)}
                      className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                      disabled={csvLoading}
                    />
                    <UploadSimple size={20} className="text-slate-400 mb-1 mx-auto" />
                    <span className="text-xs font-medium text-slate-700 block truncate">
                      {csvFile ? csvFile.name : 'Выберите .csv файл'}
                    </span>
                  </div>

                  {csvMessage && (
                    <div className={`p-3 rounded-xl flex items-start gap-2 text-xs border ${
                      csvMessage.type === 'success' 
                        ? 'bg-emerald-50 border-emerald-200 text-emerald-700' 
                        : 'bg-rose-50 border-rose-200 text-rose-700'
                    }`}>
                      {csvMessage.type === 'success' ? <CheckCircle size={16} className="shrink-0 mt-0.5" /> : <Warning size={16} className="shrink-0 mt-0.5" />}
                      <span>{csvMessage.text}</span>
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={!csvFile || csvLoading}
                    className={`w-full py-2.5 px-4 rounded-xl text-xs font-bold flex items-center justify-center gap-2 border transition-all cursor-pointer ${
                      csvFile && !csvLoading
                        ? 'bg-blue-600 hover:bg-blue-500 border-blue-500 text-white shadow-lg shadow-blue-500/20'
                        : 'bg-slate-100 border-slate-200 text-slate-400 cursor-not-allowed'
                    }`}
                  >
                    {csvLoading ? (
                      <>
                        <SpinnerGap size={16} className="animate-spin" />
                        Загрузка CSV...
                      </>
                    ) : (
                      <>
                        <UploadSimple size={16} />
                        Импортировать из CSV
                      </>
                    )}
                  </button>
                </form>
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};
