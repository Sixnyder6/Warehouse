import React, { useEffect } from 'react';
import { X, CheckCircle, Warning, Info, ArrowCircleDown, ArrowCircleUp } from '@phosphor-icons/react';

export interface ToastMessage {
  id: string;
  message: string;
  type: 'success' | 'warning' | 'info' | 'error' | 'take' | 'add';
  duration?: number;
}

interface ToastContainerProps {
  toasts: ToastMessage[];
  onDismiss: (id: string) => void;
}

export const ToastContainer: React.FC<ToastContainerProps> = ({ toasts, onDismiss }) => {
  return (
    <div className="fixed bottom-5 right-5 z-[200] flex flex-col gap-3.5 max-w-sm w-full pointer-events-none">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
};

interface ToastItemProps {
  toast: ToastMessage;
  onDismiss: (id: string) => void;
}

const ToastItem: React.FC<ToastItemProps> = ({ toast, onDismiss }) => {
  const { id, message, type, duration = 6000 } = toast;

  useEffect(() => {
    const timer = setTimeout(() => {
      onDismiss(id);
    }, duration);

    return () => clearTimeout(timer);
  }, [id, duration, onDismiss]);

  const getIconAndStyle = () => {
    switch (type) {
      case 'success':
        return {
          icon: <CheckCircle size={22} className="text-emerald-400" />,
          borderColor: 'border-emerald-500/35',
          glowColor: 'shadow-emerald-500/5',
        };
      case 'warning':
        return {
          icon: <Warning size={22} className="text-amber-400" />,
          borderColor: 'border-amber-500/35',
          glowColor: 'shadow-amber-500/5',
        };
      case 'error':
        return {
          icon: <Warning size={22} className="text-rose-400" />,
          borderColor: 'border-rose-500/35',
          glowColor: 'shadow-rose-500/5',
        };
      case 'take':
        return {
          icon: <ArrowCircleDown size={22} className="text-rose-400" />,
          borderColor: 'border-rose-500/35',
          glowColor: 'shadow-rose-500/5',
        };
      case 'add':
        return {
          icon: <ArrowCircleUp size={22} className="text-emerald-400" />,
          borderColor: 'border-emerald-500/35',
          glowColor: 'shadow-emerald-500/5',
        };
      case 'info':
      default:
        return {
          icon: <Info size={22} className="text-blue-400" />,
          borderColor: 'border-blue-500/35',
          glowColor: 'shadow-blue-500/5',
        };
    }
  };

  const { icon, borderColor, glowColor } = getIconAndStyle();

  return (
    <div
      className={`pointer-events-auto w-full bg-slate-900/95 border ${borderColor} rounded-2xl p-4 shadow-xl ${glowColor} backdrop-blur-md flex items-start gap-3.5 transition-all duration-300 animate-slide-in`}
    >
      <div className="shrink-0 mt-0.5">{icon}</div>
      <div className="flex-1">
        <p className="text-sm text-slate-200 font-medium leading-relaxed">{message}</p>
      </div>
      <button
        onClick={() => onDismiss(id)}
        className="shrink-0 p-0.5 rounded-lg bg-slate-850 hover:bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors cursor-pointer"
      >
        <X size={14} />
      </button>
    </div>
  );
};
