import axios from 'axios';

// Create configured axios client
// Since we have set up the Vite proxy, requests to /api will go directly to the backend
const client = axios.create({
  baseURL: '',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 15000,
});

// Types based on Pydantic models in app/models.py
export type UserRole = 'admin' | 'muver' | 'electrician' | 'inventory_manager' | 'technic' | 'supervisor' | 'security' | 'user';

export interface AuthState {
  is_logged_in: boolean;
  user_id: string | null;
  user_name: string | null;
  is_admin: boolean;
  role: UserRole;
  error: string | null;
  is_loading: boolean;
  is_shift_active: boolean;
  shift_start_time: number;
  is_allowed_to_work: boolean;
  shift_request_status: 'NONE' | 'PENDING' | 'APPROVED' | 'DENIED';
  version_error: boolean;
}

export interface WarehouseItem {
  id: string;
  fullName: string;
  shortName: string;
  sku?: string | null;
  description?: string | null;
  category: string;
  unit: string;
  stockCount: number;
  totalStock?: number;
  lowStockThreshold: number;
  imageUrl?: string | null;
  updatedAt?: string | null;
  isDeleted?: boolean;
}

export interface WarehouseLog {
  id: string;
  itemId: string;
  itemName: string;
  userId: string;
  userName: string;
  quantityChange: number;
  timestamp: string;
  issuerId?: string;
  issuerName?: string;
  recipientId?: string;
  recipientName?: string;
  notes?: string;
}

export interface OrderItem {
  itemId: string;
  itemName: string;
  itemImageUrl?: string | null;
  quantity: number;
  unit: string;
}

export interface WarehouseOrder {
  id: string;
  userId: string;
  userName: string;
  userRole: string;
  items: OrderItem[];
  status: 'CREATED' | 'PROCESSING' | 'READY' | 'COMPLETED' | 'CANCELLED';
  createdAt: string;
  completedAt?: string | null;
}

export interface DashboardSummary {
  totalItems: number;
  lowStockCount: number;
  activeOrdersCount: number;
  todayOperationsCount: number;
  recentLogs: WarehouseLog[];
}

export interface ForecastItem {
  itemId: string;
  itemName: string;
  sku?: string | null;
  category: string;
  imageUrl?: string | null;
  stockCount: number;
  lowStockThreshold: number;
  avgDailyConsumption: number;
  daysRemaining: number | null;
}

export interface NewsItem {
  id: string;
  title: string;
  content: string;
  tag: 'TODAY' | 'TOMORROW' | 'URGENT' | 'GENERAL';
}

export interface Employee {
  id: string;
  name: string;
  role: string;
  imageUrl?: string | null;
  phone?: string | null;
  status?: string;
}

export interface InternalUser {
  id: string;
  username: string;
  displayName: string;
  role: string;
  warehouseId: string;
  phone: string;
  lastSeen?: number;
  isShiftActive?: boolean;
  shiftStartTime?: number;
  scansToday?: number;
  batchesToday?: number;
  scanRatePerHour?: number;
}

// API Methods
export const api = {
  // Authentication
  auth: {
    async login(email: string, password: string): Promise<AuthState> {
      const { data } = await client.post<AuthState>(`/api/auth/login?login=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`);
      return data;
    },
    async logout(): Promise<AuthState> {
      const { data } = await client.post<AuthState>('/api/auth/logout');
      return data;
    },
    async getMe(): Promise<AuthState> {
      const { data } = await client.get<AuthState>('/api/auth/me');
      return data;
    },
    async getState(userId?: string): Promise<AuthState> {
      const path = userId ? `/api/auth/state?user_id=${userId}` : '/api/auth/state';
      const { data } = await client.get<AuthState>(path);
      return data;
    },
    async startShift(userId: string): Promise<AuthState> {
      const { data } = await client.post<AuthState>(`/api/auth/shift/start?user_id=${userId}`);
      return data;
    },
    async endShift(userId: string): Promise<AuthState> {
      const { data } = await client.post<AuthState>(`/api/auth/shift/end?user_id=${userId}`);
      return data;
    },
  },

  // Warehouse Items
  items: {
    async list(limit = 100): Promise<WarehouseItem[]> {
      const { data } = await client.get<WarehouseItem[]>(`/api/warehouse/items?limit=${limit}`);
      return data;
    },
    async get(id: string): Promise<WarehouseItem> {
      const { data } = await client.get<WarehouseItem>(`/api/warehouse/items/${id}`);
      return data;
    },
    async search(code: string): Promise<WarehouseItem> {
      const { data } = await client.get<WarehouseItem>(`/api/warehouse/items/search?code=${encodeURIComponent(code)}`);
      return data;
    },
    async create(item: Omit<WarehouseItem, 'id'>, userRole: string): Promise<{ success: boolean; id: string }> {
      const { data } = await client.post(`/api/warehouse/items?user_role=${userRole}`, item);
      return data;
    },
    async update(id: string, item: Partial<WarehouseItem>, userRole: string): Promise<{ success: boolean }> {
      const { data } = await client.put(`/api/warehouse/items/${id}?user_role=${userRole}`, item);
      return data;
    },
    async delete(id: string, userRole: string): Promise<{ success: boolean }> {
      const { data } = await client.delete(`/api/warehouse/items/${id}?user_role=${userRole}`);
      return data;
    },
    async take(itemId: string, quantity: number, userName: string, userId: string): Promise<{ success: boolean; message: string }> {
      const { data } = await client.post('/api/warehouse/take', { itemId, quantity, userName, userId });
      return data;
    },
    async add(itemId: string, quantity: number, userName: string, userId: string): Promise<{ success: boolean; message: string }> {
      const { data } = await client.post('/api/warehouse/add', { itemId, quantity, userName, userId });
      return data;
    },
    async takeExtended(itemId: string, quantity: number, recipientName: string, recipientId: string, notes = ''): Promise<{ success: boolean; message: string }> {
      const { data } = await client.post('/api/warehouse/take-extended', { itemId, quantity, recipientName, recipientId, notes });
      return data;
    },
    async return(itemId: string, quantity: number, recipientName: string, recipientId: string, notes = ''): Promise<{ success: boolean; message: string }> {
      const { data } = await client.post('/api/warehouse/return', { itemId, quantity, recipientName, recipientId, notes });
      return data;
    },
    async importExcel(file: File, userRole: string): Promise<{ success: boolean; task_id: string }> {
      const formData = new FormData();
      formData.append('file', file);
      const { data } = await client.post(`/api/warehouse/import-excel?user_role=${userRole}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return data;
    },
    async getImportStatus(taskId: string): Promise<{ status: string; progress: number; success_count?: number; error?: string }> {
      const { data } = await client.get(`/api/warehouse/import-excel/status/${taskId}`);
      return data;
    },
  },

  // Dashboard
  dashboard: {
    async getSummary(): Promise<DashboardSummary> {
      const { data } = await client.get<DashboardSummary>('/api/warehouse/dashboard-summary');
      return data;
    },
    async getDbTelemetry(userRole: string): Promise<any> {
      const { data } = await client.get(`/api/admin/db-telemetry?user_role=${userRole}`);
      return data;
    },
    async getOnlineUsers(): Promise<any[]> {
      const { data } = await client.get('/api/online-users');
      return data;
    },
    async getForecast(days = 30): Promise<ForecastItem[]> {
      const { data } = await client.get<ForecastItem[]>(`/api/warehouse/forecast?days=${days}`);
      return data;
    },
    async ping(userId?: string): Promise<{ success: boolean; lastSeen: number }> {
      const { data } = await client.post('/api/ping', { user_id: userId });
      return data;
    },
  },

  // Orders
  orders: {
    async list(statusFilter?: string, userId?: string, limit = 100): Promise<WarehouseOrder[]> {
      let url = `/api/warehouse/orders?limit=${limit}`;
      if (statusFilter) url += `&status=${statusFilter}`;
      if (userId) url += `&userId=${userId}`;
      const { data } = await client.get<WarehouseOrder[]>(url);
      return data;
    },
    async create(order: { userId: string; userName: string; userRole: string; items: OrderItem[] }): Promise<{ success: boolean; id: string }> {
      const { data } = await client.post('/api/warehouse/orders', order);
      return data;
    },
    async updateStatus(orderId: string, status: string): Promise<{ success: boolean }> {
      const { data } = await client.patch(`/api/warehouse/orders/${orderId}/status`, { status });
      return data;
    },
    async complete(orderId: string, warehouseManName: string): Promise<{ success: boolean; message: string }> {
      const { data } = await client.post(`/api/warehouse/orders/${orderId}/complete`, { warehouseManName });
      return data;
    },
  },

  // News
  news: {
    async list(): Promise<NewsItem[]> {
      const { data } = await client.get<NewsItem[]>('/api/warehouse/news');
      return data;
    },
    async create(news: Omit<NewsItem, 'id'>): Promise<{ success: boolean }> {
      const { data } = await client.post('/api/warehouse/news', news);
      return data;
    },
    async update(id: string, news: Omit<NewsItem, 'id'>): Promise<{ success: boolean }> {
      const { data } = await client.put(`/api/warehouse/news/${id}`, news);
      return data;
    },
    async delete(id: string): Promise<{ success: boolean }> {
      const { data } = await client.delete(`/api/warehouse/news/${id}`);
      return data;
    },
  },

  // Employees & Users
  employees: {
    async list(): Promise<Employee[]> {
      const { data } = await client.get<Employee[]>('/api/warehouse/employees');
      return data;
    },
    async listInternal(): Promise<InternalUser[]> {
      const { data } = await client.get<InternalUser[]>('/api/internal-users');
      return data;
    },
    async listPresence(): Promise<any[]> {
      const { data } = await client.get<any[]>('/api/internal-users/presence');
      return data;
    },
  },

  // History & Reports
  history: {
    async list(employee?: string, dateFrom?: string, dateTo?: string, lastTimestamp?: string): Promise<any[]> {
      let url = '/api/history';
      const params = new URLSearchParams();
      if (employee) params.append('employee', employee);
      if (dateFrom) params.append('dateFrom', dateFrom);
      if (dateTo) params.append('dateTo', dateTo);
      if (lastTimestamp) params.append('lastTimestamp', lastTimestamp);
      const queryStr = params.toString();
      if (queryStr) url += `?${queryStr}`;
      const { data } = await client.get<any[]>(url);
      return data;
    },
    async stats(dateFrom?: string, dateTo?: string): Promise<{ dates: string[]; counts: number[] }> {
      let url = '/api/history/stats';
      const params = new URLSearchParams();
      if (dateFrom) params.append('dateFrom', dateFrom);
      if (dateTo) params.append('dateTo', dateTo);
      const queryStr = params.toString();
      if (queryStr) url += `?${queryStr}`;
      const { data } = await client.get<{ dates: string[]; counts: number[] }>(url);
      return data;
    },
    async summary(employee?: string, dateFrom?: string, dateTo?: string): Promise<any> {
      let url = '/api/history/summary';
      const params = new URLSearchParams();
      if (employee) params.append('employee', employee);
      if (dateFrom) params.append('dateFrom', dateFrom);
      if (dateTo) params.append('dateTo', dateTo);
      const queryStr = params.toString();
      if (queryStr) url += `?${queryStr}`;
      const { data } = await client.get<any>(url);
      return data;
    },
  },

  // Synchronisation
  sync: {
    async pull(lastPulledAt?: string): Promise<{ items: any[]; serverTime: string }> {
      const path = lastPulledAt ? `/api/sync/pull?last_pulled_at=${encodeURIComponent(lastPulledAt)}` : '/api/sync/pull';
      const { data } = await client.get<{ items: any[]; serverTime: string }>(path);
      return data;
    },
    async push(operations: any[]): Promise<{ success_count: number; failed_count: number; errors: any[] }> {
      const { data } = await client.post('/api/sync/push', { operations });
      return data;
    },
  },
};
