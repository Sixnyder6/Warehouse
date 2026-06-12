import React, { useEffect, useRef, useState, useCallback } from 'react';
import { X, Camera, Warning, ImageSquare } from '@phosphor-icons/react';

interface BarcodeScannerProps {
  onScanSuccess: (decodedText: string) => void;
  onClose: () => void;
}

type ScanState = 'loading' | 'scanning' | 'error' | 'photo_mode';

export const BarcodeScanner: React.FC<BarcodeScannerProps> = ({ onScanSuccess, onClose }) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const animRef = useRef<number | null>(null);
  const detectorRef = useRef<any>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const galleryInputRef = useRef<HTMLInputElement>(null);
  const lastCodeRef = useRef<string>('');
  const lastTimeRef = useRef<number>(0);

  const [state, setState] = useState<ScanState>('loading');
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [photoProcessing, setPhotoProcessing] = useState(false);

  const stopCamera = useCallback(() => {
    if (animRef.current) {
      cancelAnimationFrame(animRef.current);
      animRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  }, []);

  const handleSuccess = useCallback(
    (code: string) => {
      const now = Date.now();
      // Debounce: ignore same code within 2 seconds
      if (code === lastCodeRef.current && now - lastTimeRef.current < 2000) return;
      lastCodeRef.current = code;
      lastTimeRef.current = now;

      try { navigator.vibrate?.(150); } catch {}
      stopCamera();
      onScanSuccess(code);
    },
    [onScanSuccess, stopCamera]
  );

  // ─── Main scan loop using BarcodeDetector ───────────────────────────────────
  const scanLoop = useCallback(() => {
    const video = videoRef.current;
    const detector = detectorRef.current;
    if (!video || !detector || video.paused || video.readyState < 2) {
      animRef.current = requestAnimationFrame(scanLoop);
      return;
    }

    detector
      .detect(video)
      .then((barcodes: any[]) => {
        if (barcodes.length > 0 && barcodes[0].rawValue) {
          handleSuccess(barcodes[0].rawValue);
        } else {
          animRef.current = requestAnimationFrame(scanLoop);
        }
      })
      .catch(() => {
        animRef.current = requestAnimationFrame(scanLoop);
      });
  }, [handleSuccess]);

  // ─── Camera startup ─────────────────────────────────────────────────────────
  useEffect(() => {
    const start = async () => {
      // Check BarcodeDetector support (Chrome Android 83+, Chrome Desktop 88+)
      const hasDetector = 'BarcodeDetector' in window;

      if (!hasDetector) {
        // Fallback: use photo-mode (file input with camera capture)
        setState('photo_mode');
        return;
      }

      try {
        detectorRef.current = new (window as any).BarcodeDetector({
          formats: [
            'qr_code',
            'code_128',
            'code_39',
            'ean_13',
            'ean_8',
            'upc_a',
            'upc_e',
            'data_matrix',
            'aztec',
          ],
        });

        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: 'environment' },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });

        streamRef.current = stream;

        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.onloadedmetadata = () => {
            videoRef.current?.play();
            setState('scanning');
            animRef.current = requestAnimationFrame(scanLoop);
          };
        }
      } catch (err: any) {
        console.error('Camera error:', err);
        // Always fall back to photo mode — works on HTTP, iOS Safari, any browser
        setState('photo_mode');
      }
    };

    start();
    return () => stopCamera();
  }, [scanLoop, stopCamera]);

  // ─── Photo mode: scan image file with html5-qrcode ─────────────────────────
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setPhotoProcessing(true);
    setErrorMsg('');

    try {
      // Use BarcodeDetector if available (faster, no DOM element needed)
      if ('BarcodeDetector' in window) {
        const img = new Image();
        const url = URL.createObjectURL(file);
        img.src = url;
        await new Promise<void>((res, rej) => {
          img.onload = () => res();
          img.onerror = () => rej(new Error('image load failed'));
        });
        const detector = new (window as any).BarcodeDetector({
          formats: ['qr_code', 'code_128', 'code_39', 'ean_13', 'ean_8', 'upc_a', 'upc_e', 'data_matrix', 'aztec'],
        });
        const barcodes = await detector.detect(img);
        URL.revokeObjectURL(url);
        if (barcodes.length > 0 && barcodes[0].rawValue) {
          handleSuccess(barcodes[0].rawValue);
          return;
        }
        throw new Error('no code found');
      } else {
        // Fallback: html5-qrcode instance scan
        const { Html5Qrcode } = await import('html5-qrcode');
        // html5-qrcode needs a mounted DOM element — create offscreen (not display:none!)
        const tempId = '__qr_temp_' + Date.now();
        const div = document.createElement('div');
        div.id = tempId;
        div.style.cssText = 'position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden';
        document.body.appendChild(div);
        try {
          const scanner = new Html5Qrcode(tempId);
          const result = await scanner.scanFile(file, false);
          handleSuccess(result);
        } finally {
          document.getElementById(tempId)?.remove();
        }
      }
    } catch {
      setErrorMsg('Код не распознан. Попробуйте сфотографировать чётче, при хорошем освещении.');
    } finally {
      setPhotoProcessing(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleClose = () => {
    stopCamera();
    onClose();
  };

  // ─── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="fixed inset-0 z-[100] bg-black flex flex-col" style={{ touchAction: 'none' }}>

      {/* ── Header ── */}
      <div className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between px-5 pt-safe py-4 bg-gradient-to-b from-black/70 to-transparent">
        <div className="flex items-center gap-2 text-white font-semibold text-base">
          <Camera size={20} className="text-emerald-400" weight="fill" />
          <span>Сканирование</span>
        </div>
        <button
          onClick={handleClose}
          className="w-9 h-9 flex items-center justify-center bg-white/15 hover:bg-white/25 rounded-full text-white transition-colors cursor-pointer"
        >
          <X size={20} weight="bold" />
        </button>
      </div>

      {/* ── Live camera video ── */}
      {(state === 'loading' || state === 'scanning') && (
        <video
          ref={videoRef}
          className="absolute inset-0 w-full h-full object-cover"
          playsInline
          muted
          autoPlay
        />
      )}

      {/* ── Loading spinner ── */}
      {state === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center bg-black">
          <div className="text-center space-y-3">
            <div className="w-10 h-10 border-2 border-emerald-400/30 border-t-emerald-400 rounded-full animate-spin mx-auto" />
            <p className="text-slate-400 text-sm">Запуск камеры…</p>
          </div>
        </div>
      )}

      {/* ── Live scan overlay ── */}
      {state === 'scanning' && (
        <>
          {/* Darkened vignette */}
          <div className="absolute inset-0 pointer-events-none"
            style={{
              background:
                'radial-gradient(ellipse 55% 55% at 50% 48%, transparent 58%, rgba(0,0,0,0.65) 100%)',
            }}
          />

          {/* Targeting frame */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="relative w-64 h-64">
              {/* Corner brackets */}
              {[
                'top-0 left-0 border-t-4 border-l-4 rounded-tl-xl',
                'top-0 right-0 border-t-4 border-r-4 rounded-tr-xl',
                'bottom-0 left-0 border-b-4 border-l-4 rounded-bl-xl',
                'bottom-0 right-0 border-b-4 border-r-4 rounded-br-xl',
              ].map((cls, i) => (
                <div key={i} className={`absolute w-8 h-8 border-emerald-400 ${cls}`} />
              ))}

              {/* Animated scan line */}
              <div
                className="absolute left-3 right-3 h-0.5 rounded-full bg-emerald-400"
                style={{
                  boxShadow: '0 0 10px #34d399, 0 0 20px #34d399',
                  animation: 'scanline 2s ease-in-out infinite',
                }}
              />
            </div>
          </div>

          {/* Hint at bottom */}
          <div className="absolute bottom-0 left-0 right-0 p-6 pb-safe bg-gradient-to-t from-black/75 to-transparent text-center pointer-events-none">
            <p className="text-white/80 text-sm">Наведите на штрих-код или QR-код</p>
          </div>
        </>
      )}

      {/* ── Photo mode (HTTP fallback) ── */}
      {state === 'photo_mode' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-950 px-6 gap-6">
          <div className="w-20 h-20 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
            <Camera size={40} className="text-emerald-400" weight="fill" />
          </div>

          <div className="text-center space-y-2">
            <p className="text-white font-bold text-lg">Фото-сканирование</p>
            <p className="text-slate-400 text-sm leading-relaxed max-w-xs">
              Камера недоступна по прямой ссылке — нужен HTTPS.
              Используйте кнопку ниже: откроется камера телефона,
              сфотографируйте код — он распознается автоматически.
            </p>
          </div>

          {errorMsg && (
            <div className="w-full max-w-xs bg-rose-500/10 border border-rose-500/20 rounded-xl px-4 py-3 flex items-start gap-2">
              <Warning size={16} className="text-rose-400 mt-0.5 shrink-0" />
              <p className="text-rose-300 text-xs">{errorMsg}</p>
            </div>
          )}

          <div className="w-full max-w-xs space-y-3">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={photoProcessing}
              className="w-full py-4 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white rounded-2xl font-semibold flex items-center justify-center gap-2 transition-colors cursor-pointer text-base shadow-lg shadow-emerald-900/30"
            >
              {photoProcessing ? (
                <>
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Распознаём…
                </>
              ) : (
                <>
                  <Camera size={20} weight="fill" />
                  Сфотографировать код
                </>
              )}
            </button>

            <button
              onClick={() => galleryInputRef.current?.click()}
              disabled={photoProcessing}
              className="w-full py-3 bg-white/8 hover:bg-white/12 text-slate-300 rounded-2xl font-medium flex items-center justify-center gap-2 transition-colors cursor-pointer text-sm border border-white/10"
            >
              <ImageSquare size={16} />
              Выбрать из галереи
            </button>

            <button
              onClick={handleClose}
              className="w-full py-3 text-slate-500 text-sm cursor-pointer"
            >
              Закрыть
            </button>
          </div>
        </div>
      )}

      {state === 'error' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-950 px-6 gap-5">
          <Warning size={44} className="text-rose-500" />
          <p className="text-white font-bold text-lg">Ошибка камеры</p>
          <p className="text-slate-400 text-sm text-center max-w-xs">{errorMsg}</p>
          <button
            onClick={() => setState('photo_mode')}
            className="px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-medium cursor-pointer"
          >
            Использовать фото
          </button>
          <button onClick={handleClose} className="text-slate-500 text-sm cursor-pointer">
            Закрыть
          </button>
        </div>
      )}

      {/* ── Hidden file inputs ── */}
      {/* Camera capture (opens camera directly) */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={handleFileChange}
        className="hidden"
      />
      {/* Gallery picker (no capture — opens gallery) */}
      <input
        ref={galleryInputRef}
        type="file"
        accept="image/*"
        onChange={handleFileChange}
        className="hidden"
      />

      {/* ── Scan line CSS animation ── */}
      <style>{`
        @keyframes scanline {
          0%   { top: 10%; opacity: 1; }
          50%  { top: 88%; opacity: 0.8; }
          100% { top: 10%; opacity: 1; }
        }
      `}</style>
    </div>
  );
};
