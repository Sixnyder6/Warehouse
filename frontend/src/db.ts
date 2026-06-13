import Dexie, { type Table } from 'dexie';
import { api, type WarehouseItem, type WarehouseLog, type WarehouseOrder, type InternalUser } from './api';

// Sync queue operation type
export interface OfflineOperation {
  id: string; // client UUID or timestamp-generated ID
  type: 'TAKE' | 'ADD' | 'TAKE_EXTENDED' | 'RETURN';
  itemId: string;
  quantity: number;
  userName: string;
  userId: string;
  recipientName?: string;
  recipientId?: string;
  notes?: string;
  timestamp: string; // ISO string representing when worker triggered it
}

export class WarehouseDatabase extends Dexie {
  items!: Table<WarehouseItem, string>;
  logs!: Table<WarehouseLog, string>;
  orders!: Table<WarehouseOrder, string>;
  syncQueue!: Table<OfflineOperation, string>;
  employees!: Table<InternalUser, string>;

  constructor() {
    super('WarehouseDatabase');
    this.version(2).stores({
      items: 'id, shortName, sku, category, updatedAt, isDeleted',
      logs: 'id, itemId, userId, timestamp',
      orders: 'id, status, userId, createdAt',
      syncQueue: 'id, itemId, type, timestamp',
      employees: 'id, username, displayName, role'
    });
  }
}

export const db = new WarehouseDatabase();

// Connection state tracking helpers
let isSyncing = false;
let syncListeners: ((syncing: boolean) => void)[] = [];
let onNetworkStateChange: ((online: boolean) => void) | null = null;

export function registerSyncStateListener(callback: (syncing: boolean) => void) {
  syncListeners.push(callback);
  // Call immediately with the current state
  callback(isSyncing);
  // Return cleanup function to unsubscribe
  return () => {
    syncListeners = syncListeners.filter(cb => cb !== callback);
  };
}

export function registerNetworkStateListener(callback: (online: boolean) => void) {
  onNetworkStateChange = callback;
  // Trigger initial check
  callback(navigator.onLine);
}

// Event listeners for browser online/offline status
window.addEventListener('online', () => {
  if (onNetworkStateChange) onNetworkStateChange(true);
  triggerSync();
});

window.addEventListener('offline', () => {
  if (onNetworkStateChange) onNetworkStateChange(false);
});

// Cache the active sync operation promise to share it among concurrent callers
let activeSyncPromise: Promise<{ success: boolean; pushed: number; pulled: number; errors?: any[] }> | null = null;

/**
 * Triggers full offline synchronization:
 * 1. PUSH: Sends offline operations queue to the backend.
 * 2. PULL: Retrieves server updates (delta or full) and stores them locally.
 */
export async function triggerSync(): Promise<{ success: boolean; pushed: number; pulled: number; errors?: any[] }> {
  if (!navigator.onLine) {
    return { success: false, pushed: 0, pulled: 0 };
  }

  if (activeSyncPromise) {
    return activeSyncPromise;
  }

  activeSyncPromise = (async () => {
    isSyncing = true;
    syncListeners.forEach(cb => {
      try { cb(true); } catch (e) { console.error(e); }
    });

    const results = { success: true, pushed: 0, pulled: 0, errors: [] as any[] };

    try {
      // 1. PUSH: Fetch pending operations
      const pendingOps = await db.syncQueue.toArray();
      if (pendingOps.length > 0) {
        // Map properties to server structure
        const serverOps = pendingOps.map(op => ({
          id: op.id,
          type: op.type === 'TAKE_EXTENDED' ? 'TAKE' : op.type === 'RETURN' ? 'ADD' : op.type, // server processes TAKE or ADD
          itemId: op.itemId,
          quantity: op.quantity,
          userName: op.type === 'TAKE_EXTENDED' ? `${op.recipientName} (выдал ${op.userName})` : op.type === 'RETURN' ? `${op.recipientName} (принял ${op.userName})` : op.userName,
          userId: op.userId,
          timestamp: op.timestamp,
          notes: op.notes || '',
        }));

        const pushResult = await api.sync.push(serverOps);
        results.pushed = pushResult.success_count;

        if (pushResult.failed_count > 0) {
          results.errors = pushResult.errors;
          // Remove successfully processed operations from local queue, keep failed ones
          const failedIds = new Set(pushResult.errors.map(e => e.id));
          const successOps = pendingOps.filter(op => !failedIds.has(op.id));
          await db.syncQueue.bulkDelete(successOps.map(op => op.id));
        } else {
          // All succeeded, clear entire queue
          await db.syncQueue.clear();
        }
      }

      // 2. PULL: Get latest updates
      // Find the latest updatedAt timestamp among local items
      const lastItem = await db.items.orderBy('updatedAt').reverse().first();
      const lastPulledAt = lastItem?.updatedAt || undefined;

      const pullResult = await api.sync.pull(lastPulledAt);
      const serverItems = JSON.parse(JSON.stringify(pullResult.items));
      results.pulled = serverItems.length;

      if (serverItems.length > 0) {
        // Save items to local IndexedDB (updates or inserts)
        await db.transaction('rw', db.items, async () => {
          for (const item of serverItems) {
            if (item.isDeleted) {
              await db.items.delete(item.id);
            } else {
              // Normalize structure if necessary
              await db.items.put({
                id: item.id || '',
                fullName: item.fullName || '',
                shortName: item.shortName || '',
                sku: item.sku || null,
                description: item.description || null,
                category: item.category || 'Общее',
                unit: item.unit || 'шт.',
                stockCount: typeof item.stockCount === 'number' ? item.stockCount : 0,
                totalStock: typeof item.totalStock === 'number' ? item.totalStock : 0,
                lowStockThreshold: typeof item.lowStockThreshold === 'number' ? item.lowStockThreshold : 10,
                imageUrl: item.imageUrl || null,
                updatedAt: item.updatedAt || new Date().toISOString(),
                isDeleted: false
              });
            }
          }
        });
      }

      // 3. PULL NEW LOGS (DELTA SYNC)
      const localLogsCount = await db.logs.count();
      const lastLog = await db.logs.orderBy('timestamp').reverse().first();
      const lastLogTimestamp = (localLogsCount >= 1000 && lastLog) ? lastLog.timestamp : undefined;
      const freshLogs = await api.history.list(
        undefined,
        undefined,
        undefined,
        lastLogTimestamp
      );
      if (freshLogs.length > 0) {
        await db.transaction('rw', db.logs, async () => {
          if (!lastLogTimestamp) {
            await db.logs.clear();
          }
          await db.logs.bulkPut(freshLogs);
        });
      }

      // 4. PULL ALL EMPLOYEES
      const freshEmployees = await api.employees.listInternal();
      if (freshEmployees.length > 0) {
        await db.transaction('rw', db.employees, async () => {
          await db.employees.clear();
          await db.employees.bulkPut(freshEmployees);
        });
      }
    } catch (error) {
      console.error('Offline synchronization failed:', error);
      results.success = false;
    } finally {
      isSyncing = false;
      syncListeners.forEach(cb => {
        try { cb(false); } catch (e) { console.error(e); }
      });
      activeSyncPromise = null;
    }

    return results;
  })();

  return activeSyncPromise;
}

/**
 * Optimistic action helper. Instantly updates local item stock and queues the operation in the background.
 */
export async function performOptimisticStockOperation(
  type: 'TAKE' | 'ADD' | 'TAKE_EXTENDED' | 'RETURN',
  itemId: string,
  quantity: number,
  userName: string,
  userId: string,
  recipientName = '',
  recipientId = '',
  notes = ''
): Promise<{ success: boolean; message: string }> {
  try {
    const item = await db.items.get(itemId);
    if (!item) {
      return { success: false, message: 'Товар не найден в локальной базе' };
    }

    const currentStock = item.stockCount;
    const isDecrement = type === 'TAKE' || type === 'TAKE_EXTENDED';

    if (isDecrement && currentStock < quantity) {
      return { success: false, message: `Недостаточно остатка! В наличии: ${currentStock}` };
    }

    // Determine target stock change
    const delta = isDecrement ? -quantity : quantity;
    const newStock = currentStock + delta;

    // 1. Optimistic Update in Local DB
    await db.items.update(itemId, { stockCount: newStock, updatedAt: new Date().toISOString() });

    // 2. Add operation to offline queue
    const opId = `local_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    const op: OfflineOperation = {
      id: opId,
      type,
      itemId,
      quantity,
      userName,
      userId,
      recipientName: recipientName || undefined,
      recipientId: recipientId || undefined,
      notes: notes || undefined,
      timestamp: new Date().toISOString(),
    };
    await db.syncQueue.add(op);

    // 3. Trigger async background synchronization (runs in parallel, non-blocking)
    triggerSync().catch(err => console.error('Background sync failed:', err));

    const changeMsg = isDecrement ? `-${quantity}` : `+${quantity}`;
    return { 
      success: true, 
      message: `[Локально] ${item.shortName}: ${changeMsg} ${item.unit}` 
    };
  } catch (err) {
    console.error('Optimistic stock operation failed:', err);
    return { success: false, message: `Ошибка локального обновления: ${String(err)}` };
  }
}
