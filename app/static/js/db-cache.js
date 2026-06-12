/**
 * db-cache.js
 * Локальное хранилище и мост к фоновому Web Worker'у (Сетевому движку).
 */

const dexieScript = document.createElement('script');
dexieScript.src = "/static/js/dexie.js";
document.head.appendChild(dexieScript);

let localDB;
let syncWorker = null;

dexieScript.onload = () => {
    initLocalDB();
    initSyncWorker();
};

function initLocalDB() {
    console.log("📦 Инициализация IndexedDB...");
    localDB = new Dexie("WarehouseOfflineDB");
    localDB.version(1).stores({
        items: "id, shortName, sku, category, stockCount, updatedAt, isDeleted",
        sync_queue: "id, type, itemId, quantity, userName, userId, timestamp"
    });
}

function initSyncWorker() {
    if (window.Worker) {
        syncWorker = new Worker('/static/js/sync-worker.js');
        
        syncWorker.onmessage = function(e) {
            const msg = e.data;
            if (msg.type === "connection_status") {
                console.log(msg.connected ? "🟢 Синхронизатор онлайн" : "🔴 Синхронизатор офлайн");
                if (typeof window.realtime !== 'undefined' && window.realtime.setOnConnectionChangeCallback) {
                    window.realtime.setOnConnectionChangeCallback(msg.connected);
                }
            } else if (msg.type === "data_updated") {
                if (typeof triggerUIRefresh === "function") {
                    triggerUIRefresh();
                }
            }
        };

        // Запускаем воркер
        syncWorker.postMessage({ type: 'init' });
    } else {
        console.warn("Браузер не поддерживает Web Workers. Фоновая синхронизация отключена.");
    }
}

/**
 * Быстрая операция "Взять" или "Добавить"
 * Сначала мгновенно меняет данные локально, а потом сообщает Worker'у.
 */
async function executeLocalOperation(type, itemId, quantity, userName, userId) {
    if (!localDB) {
        console.error("База данных не инициализирована");
        return { success: false, detail: "Ошибка БД" };
    }

    try {
        const item = await localDB.items.get(itemId);
        if (!item) return { success: false, detail: "Товар не найден" };

        const change = type === "TAKE" ? -quantity : quantity;
        const newStock = item.stockCount + change;

        if (type === "TAKE" && newStock < 0) {
            return { success: false, detail: `Недостаточно на складе! В наличии всего: ${item.stockCount}` };
        }

        // 1. Оптимистичное обновление
        item.stockCount = newStock;
        item.updatedAt = new Date().toISOString();
        await localDB.items.put(item);

        // 2. Очередь
        const opId = "op_" + Math.random().toString(36).substr(2, 9) + "_" + Date.now();
        await localDB.sync_queue.put({
            id: opId,
            type: type,
            itemId: itemId,
            quantity: quantity,
            userName: userName,
            userId: userId,
            timestamp: new Date().toISOString()
        });

        // 3. Обновляем экран сразу
        if (typeof triggerUIRefresh === "function") {
            triggerUIRefresh();
        }

        // 4. Пингуем воркер, чтобы он сразу отправил на сервер
        if (syncWorker) {
            syncWorker.postMessage({ type: 'local_operation_added' });
        }

        return { success: true, detail: `${item.shortName}: ${change > 0 ? '+' : ''}${change} ${item.unit || 'шт'}` };

    } catch (e) {
        console.error("Ошибка локальной операции:", e);
        return { success: false, detail: "Ошибка базы данных" };
    }
}