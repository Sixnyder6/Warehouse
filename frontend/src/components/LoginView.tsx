import React, { useState } from 'react';
import { api, type AuthState } from '../api';
import { Lock, EnvelopeSimple, SpinnerGap } from '@phosphor-icons/react';

interface LoginViewProps {
  onLoginSuccess: (state: AuthState) => void;
}

export const LoginView: React.FC<LoginViewProps> = ({ onLoginSuccess }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError('Заполните все поля');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const state = await api.auth.login(email.trim(), password);
      if (state.error) {
        setError(state.error);
      } else if (state.is_logged_in) {
        onLoginSuccess(state);
      } else {
        setError('Не удалось войти. Проверьте учетные данные.');
      }
    } catch (err: any) {
      console.error(err);
      const detail = err.response?.data?.detail;
      const errorMsg = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d.msg ?? JSON.stringify(d)).join(', ')
          : 'Ошибка соединения с сервером';
      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4 relative overflow-hidden">
      {/* Dynamic Background Glows */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-blue-500/20 rounded-full blur-[100px] pointer-events-none"></div>
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-purple-500/20 rounded-full blur-[100px] pointer-events-none"></div>

      <div className="w-full max-w-md bg-white p-8 rounded-2xl border border-slate-200 shadow-xl relative z-10 animate-fade-in">
        <div className="text-center mb-8">
          <div className="inline-flex p-3 bg-blue-50 text-blue-600 rounded-xl mb-3 border border-blue-200">
            <Lock size={32} weight="bold" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-800 mb-2">
            Склад Бестужевская 10
          </h1>
          <p className="text-slate-500 text-sm">
            Введите учетные данные для доступа к панели управления
          </p>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-rose-50 border border-rose-200 text-rose-700 rounded-xl text-sm leading-relaxed">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-slate-700 text-sm font-medium mb-1.5" htmlFor="email">
              Электронная почта (Email)
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-slate-500">
                <EnvelopeSimple size={20} />
              </span>
              <input
                id="email"
                type="email"
                placeholder="admin@warehouse.ru"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={loading}
                className="w-full pl-11 pr-4 py-3 bg-slate-50 border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 placeholder-slate-400 focus:outline-none transition-all duration-200 text-sm"
              />
            </div>
          </div>

          <div>
            <label className="block text-slate-700 text-sm font-medium mb-1.5" htmlFor="password">
              Пароль
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-slate-500">
                <Lock size={20} />
              </span>
              <input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
                className="w-full pl-11 pr-4 py-3 bg-slate-50 border border-slate-200 focus:border-blue-500 rounded-xl text-slate-800 placeholder-slate-400 focus:outline-none transition-all duration-200 text-sm"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 text-white font-medium py-3 rounded-xl transition-all duration-150 focus:outline-none shadow-lg shadow-blue-500/20 disabled:opacity-50 text-sm mt-8 cursor-pointer"
          >
            {loading ? (
              <>
                <SpinnerGap size={18} className="animate-spin" />
                Вход в систему...
              </>
            ) : (
              'Войти в панель'
            )}
          </button>
        </form>

        <div className="mt-8 text-center text-xs text-slate-400">
          WMS System v2.0 • Разработано для Бестужевская 10
        </div>
      </div>
    </div>
  );
};
