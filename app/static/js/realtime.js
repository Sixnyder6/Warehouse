/**
 * realtime.js
 * Подписка на изменения Firestore в реальном времени (onSnapshot).
 * 
 * ОБЯЗАННОСТИ:
 *  - Подписывается на коллекцию warehouse_logs (последние 50 записей)
 *  - При новом логе вызывает callback onNewLog(log)
 *  - При изменении остатков вызывает callback onStockChange(itemId, newQty)
 * 
 * Зависимости: Firebase SDK (загружается из CDN)
 */

// ==========================================
// ИНИЦИАЛИЗАЦИЯ FIREBASE SDK
// ==========================================

// Загружаем Firebase SDK, если ещё не загружен
(function loadFirebaseSDK() {
    if (typeof firebase !== 'undefined') return;

    const script = document.createElement('script');
    script.src = "/static/js/firebase-app-compat.js";
    document.head.appendChild(script);

    const firestoreScript = document.createElement('script');
    firestoreScript.src = "/static/js/firebase-firestore-compat.js";
    document.head.appendChild(firestoreScript);

    // После загрузки обеих библиотек — инициализируем
    let loadedCount = 0;
    const onLoad = () => {
        loadedCount++;
        if (loadedCount === 2) {
            initRealtime();
        }
    };
    script.onload = onLoad;
    firestoreScript.onload = onLoad;

    // Фолбэк если скрипты уже загружены
    setTimeout(() => {
        if (typeof firebase !== 'undefined' && typeof firebase.firestore !== 'undefined') {
            initRealtime();
        }
    }, 3000);
})();

// Firebase конфигурация (должна быть вынесена в .env в проде)
const FIREBASE_CONFIG = {
    apiKey: "AIzaSyB-F6T8iK8QZnS8pC8J8z8d8f8g8h8i8j8",
    authDomain: "warehouse-app.firebaseapp.com",
    projectId: "warehouse-app",
    storageBucket: "warehouse-app.appspot.com",
    messagingSenderId: "123456789",
    appId: "1:123456789:web:abcdef123456"
};

// Callbacks (устанавливаются из dashboard.html)
let onNewLogCallback = null;
let onStockChangeCallback = null;
let onConnectionChangeCallback = null;

/**
 * Устанавливает callback для нового лога
 */
function setOnNewLog(callback) {
    onNewLogCallback = callback;
}

/**
 * Устанавливает callback для изменения остатка
 */
function setOnStockChange(callback) {
    onStockChangeCallback = callback;
}

/**
 * Устанавливает callback для статуса подключения
 */
function setOnConnectionChange(callback) {
    onConnectionChangeCallback = callback;
}

let db = null;
let logsUnsubscribe = null;
let isRealtimeReady = false;

/**
 * Инициализация real-time подписок
 */
function initRealtime() {
    try {
        // Инициализируем Firebase приложение
        if (!firebase.apps.length) {
            firebase.initializeApp(FIREBASE_CONFIG);
        }
        
        db = firebase.firestore();
        
        // Включаем persistence (кэш в IndexedDB) — данные остаются при перезагрузке
        db.enablePersistence({ synchronizeTabs: true })
            .then(() => {
                console.log("📦 Firestore persistence включён (multi-tab)");
            })
            .catch((err) => {
                if (err.code === 'failed-precondition') {
                    console.warn("⚠️ Несколько вкладок: persistence работает в одной");
                } else if (err.code === 'unimplemented') {
                    console.warn("⚠️ Браузер не поддерживает persistence");
                }
            });
        
        // Подписываемся на статус соединения
        firebase.firestore().enableNetwork();
        
        db.collection("__metrics")
            .doc("__health")
            .onSnapshot((snapshot) => {
                // Просто проверка что onSnapshot работает
                console.log("🟢 Firebase real-time подключён");
                isRealtimeReady = true;
                if (onConnectionChangeCallback) {
                    onConnectionChangeCallback(true);
                }
            }, (error) => {
                // Если ошибка — вероятно нет прав, но мы всё равно работаем через REST API
                console.log("ℹ️ Firestore onSnapshot: нет прямого доступа (работаем через REST)");
                isRealtimeReady = false;
                if (onConnectionChangeCallback) {
                    onConnectionChangeCallback(false);
                }
            });
        
        // Подписываемся на warehouse_logs
        subscribeToLogs();
        
    } catch (e) {
        console.warn("⚠️ Не удалось инициализировать Firestore real-time:", e.message);
        // Работаем через REST API (pull каждые 120 сек)
        isRealtimeReady = false;
        if (onConnectionChangeCallback) {
            onConnectionChangeCallback(false);
        }
    }
}

/**
 * Подписка на последние 50 логов
 */
function subscribeToLogs() {
    if (!db) return;
    
    // Отписываемся от предыдущей подписки
    if (logsUnsubscribe) {
        logsUnsubscribe();
    }
    
    try {
        const logsQuery = db.collection("warehouse_logs")
            .orderBy("timestamp", "desc")
            .limit(50);
        
        logsUnsubscribe = logsQuery.onSnapshot((snapshot) => {
            snapshot.docChanges().forEach((change) => {
                if (change.type === "added") {
                    const logData = change.doc.data();
                    logData.id = change.doc.id;
                    
                    if (onNewLogCallback) {
                        onNewLogCallback(logData);
                    }
                }
            });
        }, (error) => {
            console.warn("⚠️ Firestore logs subscription error:", error.message);
            // Если нет прав на прямой доступ — работаем через REST API
            isRealtimeReady = false;
        });
    } catch (e) {
        console.warn("⚠️ Не удалось подписаться на логи:", e.message);
    }
}

/**
 * Получение логов через REST API (фолбэк, если onSnapshot недоступен)
 */
async function fetchLogsViaAPI(limit = 20) {
    try {
        const response = await fetch(`/api/warehouse/logs?limit=${limit}`);
        if (response.ok) {
            return await response.json();
        }
    } catch (e) {
        console.warn("⚠️ Ошибка получения логов через API:", e);
    }
    return [];
}

/**
 * Получение списка сотрудников для формы выдачи
 */
async function fetchEmployees() {
    try {
        const response = await fetch('/api/internal-users');
        if (response.ok) {
            return await response.json();
        }
    } catch (e) {
        console.warn("⚠️ Ошибка получения сотрудников:", e);
    }
    return [];
}

/**
 * Получение списка товаров для формы выдачи
 */
async function fetchItems(search = "") {
    try {
        let url = '/api/warehouse/items?limit=50';
        if (search) {
            url = `/api/warehouse/items/search?code=${encodeURIComponent(search)}`;
        }
        const response = await fetch(url);
        if (response.ok) {
            return await response.json();
        }
    } catch (e) {
        console.warn("⚠️ Ошибка получения товаров:", e);
    }
    return [];
}

/**
 * Выдача товара сотруднику (через REST API)
 */
async function issueItem(itemId, quantity, recipientName, recipientId, notes = "") {
    try {
        const response = await fetch('/api/warehouse/take-extended', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                itemId,
                quantity,
                recipientName,
                recipientId,
                notes
            })
        });
        return await response.json();
    } catch (e) {
        console.error("❌ Ошибка выдачи:", e);
        return { success: false, message: "Ошибка сети" };
    }
}

/**
 * Возврат товара от сотрудника
 */
async function returnItem(itemId, quantity, recipientName, recipientId, notes = "") {
    try {
        const response = await fetch('/api/warehouse/return', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                itemId,
                quantity,
                recipientName,
                recipientId,
                notes
            })
        });
        return await response.json();
    } catch (e) {
        console.error("❌ Ошибка возврата:", e);
        return { success: false, message: "Ошибка сети" };
    }
}

// Экспортируем в глобальную область
window.realtime = {
    setOnNewLog,
    setOnStockChange,
    setOnConnectionChange,
    isRealtimeReady: () => isRealtimeReady,
    fetchLogsViaAPI,
    fetchEmployees,
    fetchItems,
    issueItem,
    returnItem,
    initRealtime,
};