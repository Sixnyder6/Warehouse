/**
 * sync-worker.js
 * Сверхэффективный сетевой движок (Web Worker)
 * 
 * Осуществляет фоновую синхронизацию через WebSocket с сервером.
 * Обновляет локальную базу данных (IndexedDB) напрямую, не блокируя UI.
 */

// Подключаем Dexie.js для работы с IndexedDB внутри Worker'a
importScripts("/static/js/dexie.js");

let localDB;
let ws;
const WS_URL = ((self.location.protocol === "https:") ? "wss://" : "ws://") + self.location.host + "/api/ws/sync";

// Инициализация локальной БД
function initLocalDB() {
    localDB = new Dexie("WarehouseOfflineDB");
    localDB.version(1).stores({
        items: "id, shortName, sku, category, stockCount, updatedAt, isDeleted",
        sync_queue: "id, type, itemId, quantity, userName, userId, timestamp"
    });
}

function connectWebSocket() {
    ws = new WebSocket(WS_URL);

    ws.onopen = async () => {
        console.log("[Worker] 🟢 WebSocket подключен");
        // Сообщаем главному потоку, что мы онлайн
        postMessage({ type: "connection_status", connected: true });
        
        // Как только подключились — сливаем офлайн-очередь
        await pushLocalChanges();
        // И запрашиваем обновления с сервера
        await requestPull();
    };

    ws.onmessage = async (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === "pull_response") {
                await handlePullResponse(data.items);
            } else if (data.type === "push_response") {
                if (data.success) {
                    console.log("[Worker] ✅ Очередь успешно отправлена");
                    await localDB.sync_queue.clear();
                    await requestPull();
                } else {
                    console.error("[Worker] ❌ Ошибка push:", data.error);
                }
            }
        } catch (e) {
            console.error("[Worker] Ошибка обработки сообщения WS:", e);
        }
    };

    ws.onclose = () => {
        console.warn("[Worker] 🔴 WebSocket отключен. Повтор через 5 секунд...");
        postMessage({ type: "connection_status", connected: false });
        setTimeout(connectWebSocket, 5000);
    };

    ws.onerror = (err) => {
        console.error("[Worker] ⚠️ Ошибка WebSocket:", err);
        ws.close();
    };
}

async function requestPull() {
    if (ws.readyState !== WebSocket.OPEN) return;
    
    try {
        const lastItem = await localDB.items.orderBy("updatedAt").last();
        let lastPulledAt = null;
        if (lastItem && lastItem.updatedAt) {
            lastPulledAt = lastItem.updatedAt;
        }
        
        ws.send(JSON.stringify({
            action: "pull",
            last_pulled_at: lastPulledAt
        }));
    } catch (e) {
        console.error("[Worker] Ошибка при формировании pull-запроса", e);
    }
}

async function handlePullResponse(items) {
    if (!items || items.length === 0) return;
    
    console.log(`[Worker] 📥 Получено изменений с сервера: ${items.length}`);
    await localDB.transaction('rw', localDB.items, async () => {
        for (const item of items) {
            if (item.isDeleted) {
                await localDB.items.delete(item.id);
            } else {
                await localDB.items.put(item);
            }
        }
    });
    
    // Сообщаем UI о необходимости обновить экран
    postMessage({ type: "data_updated" });
}

async function pushLocalChanges() {
    if (ws.readyState !== WebSocket.OPEN) return;
    
    const queue = await localDB.sync_queue.toArray();
    if (queue.length === 0) return;

    console.log(`[Worker] 📤 Отправка офлайн-операций: ${queue.length}`);
    ws.send(JSON.stringify({
        action: "push",
        operations: queue
    }));
}

// Прием сообщений от главного потока (UI)
self.onmessage = async (event) => {
    const msg = event.data;
    
    if (msg.type === "init") {
        initLocalDB();
        connectWebSocket();
    } else if (msg.type === "local_operation_added") {
        // UI добавил операцию в IndexedDB. Пытаемся сразу отправить на сервер.
        await pushLocalChanges();
    }
};
