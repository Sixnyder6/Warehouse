import React, { useRef, useState } from 'react';
import { UploadSimple, X, Image } from '@phosphor-icons/react';

interface ImageUploaderProps {
  currentUrl: string;
  onUploaded: (url: string) => void;
}

export const ImageUploader: React.FC<ImageUploaderProps> = ({ currentUrl, onUploaded }) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Сбросить значение input чтобы можно было выбрать тот же файл снова
    e.target.value = '';

    setError(null);
    setUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch('/api/warehouse/upload-image', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Ошибка ${res.status}`);
      }

      const data = await res.json();
      if (data.url) {
        onUploaded(data.url);
      } else {
        throw new Error('Нет URL в ответе сервера');
      }
    } catch (err: any) {
      setError(err.message || 'Не удалось загрузить фото');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-2">
      {/* Превью текущего фото */}
      {currentUrl ? (
        <div className="relative w-full h-36 rounded-xl overflow-hidden border border-slate-200 bg-slate-50 group">
          <img
            src={currentUrl}
            alt="Фото товара"
            className="w-full h-full object-contain"
          />
          <button
            type="button"
            onClick={() => onUploaded('')}
            className="absolute top-2 right-2 p-1 bg-white/90 hover:bg-rose-50 text-slate-500 hover:text-rose-500 rounded-lg border border-slate-200 transition-colors cursor-pointer opacity-0 group-hover:opacity-100"
            title="Удалить фото"
          >
            <X size={14} />
          </button>
          {/* Кнопка замены фото поверх превью */}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            className="absolute bottom-2 right-2 flex items-center gap-1.5 px-3 py-1.5 bg-white/90 hover:bg-white text-slate-700 text-xs font-semibold rounded-lg border border-slate-200 shadow-sm transition-colors cursor-pointer opacity-0 group-hover:opacity-100"
          >
            <UploadSimple size={13} />
            Заменить
          </button>
        </div>
      ) : (
        /* Зона загрузки — нет фото */
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="w-full h-24 border-2 border-dashed border-slate-300 hover:border-blue-400 rounded-xl flex flex-col items-center justify-center gap-2 transition-colors cursor-pointer bg-slate-50 hover:bg-blue-50 group"
        >
          {uploading ? (
            <>
              <div className="w-5 h-5 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
              <span className="text-xs text-slate-500">Загрузка...</span>
            </>
          ) : (
            <>
              <Image size={24} className="text-slate-400 group-hover:text-blue-500 transition-colors" />
              <span className="text-xs text-slate-500 group-hover:text-blue-600 transition-colors font-medium">
                Нажмите чтобы загрузить фото
              </span>
              <span className="text-xs text-slate-400">JPG, PNG, WEBP — до 10 МБ</span>
            </>
          )}
        </button>
      )}

      {/* Полоса загрузки */}
      {uploading && currentUrl && (
        <div className="flex items-center gap-2 text-xs text-blue-600">
          <div className="w-4 h-4 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
          Загружаем фото...
        </div>
      )}

      {/* Ошибка */}
      {error && (
        <p className="text-xs text-rose-500 flex items-center gap-1">
          <X size={12} /> {error}
        </p>
      )}

      {/* Скрытый input */}
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif"
        onChange={handleFileChange}
        className="hidden"
      />
    </div>
  );
};
