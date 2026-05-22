// Используем универсальный chrome.storage
const storage = chrome.storage.local;

function loadItems() {
    storage.get(["items"], (data) => {
        const items = data.items || [];
        const list = document.getElementById("list");
        list.innerHTML = "";

        if (items.length === 0) {
            list.innerHTML = "<div style='text-align:center; color:#8f98a0; padding:20px 0;'>List is empty</div>";
            return;
        }

        for (const item of items) {
            const div = document.createElement("div");
            div.className = "item";
            div.innerHTML = `
                <div class="item-title">${item.title}</div>
                <div class="item-id">ID: ${item.id}</div>
            `;
            list.appendChild(div);
        }
    });
}

// Надежный экспорт в TXT через Blob
function exportTXT() {
    storage.get(["items"], (data) => {
        const items = data.items || [];
        if (items.length === 0) return;

        const text = items.map(item => item.id).join("\n");
        const blob = new Blob([text], { type: "text/plain" });
        const url = URL.createObjectURL(blob);

        const a = document.createElement("a");
        a.href = url;
        a.download = "mods.txt";
        document.body.appendChild(a);
        a.click();
        
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });
}

function copyIDs() {
    storage.get(["items"], (data) => {
        const items = data.items || [];
        if (items.length === 0) return;

        const text = items.map(item => item.id).join("\n");
        navigator.clipboard.writeText(text).then(() => {
            const btn = document.getElementById("copyBtn");
            const originalText = btn.textContent;
            btn.textContent = "Copied!";
            setTimeout(() => btn.textContent = originalText, 1500);
        });
    });
}

function clearList() {
    if (!confirm("Clear all items?")) return;
    storage.set({ items: [] }, () => {
        loadItems();
    });
}

document.getElementById("exportBtn").onclick = exportTXT;
document.getElementById("copyBtn").onclick = copyIDs;
document.getElementById("clearBtn").onclick = clearList; // Этот листенер был пропущен

loadItems();