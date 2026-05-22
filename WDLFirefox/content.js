function getWorkshopID() {
    const url = new URL(window.location.href);
    return url.searchParams.get("id");
}

function getWorkshopTitle() {
    const titleElement = document.querySelector(".workshopItemTitle");
    return titleElement ? titleElement.textContent.trim() : "Unknown Item";
}

function addWorkshopItem() {
    const id = getWorkshopID();
    const title = getWorkshopTitle();

    if (!id) {
        showNotification("ID не найден", "#a93226");
        return;
    }

    chrome.storage.local.get(["items"], (data) => {
        let items = data.items || [];

        // проверка дубликатов
        if (items.some(item => item.id === id)) {
            showNotification("Уже в списке!", "#a93226");
            return;
        }

        items.push({ id, title });
        
        chrome.storage.local.set({ items }, () => {
            showNotification("Добавлено!", "#5c7e10");
        });
    });
}

// Визуальное уведомление прямо на кнопке
function showNotification(text, bgColor) {
    const btn = document.getElementById("workshopdl-btn");
    if (!btn) return;

    const originalText = btn.textContent;
    const originalBg = btn.style.background;

    btn.textContent = text;
    btn.style.background = bgColor;

    setTimeout(() => {
        btn.textContent = originalText;
        btn.style.background = originalBg;
    }, 1500);
}

function createButton() {
    if (document.getElementById("workshopdl-btn")) return;

    const button = document.createElement("button");
    button.id = "workshopdl-btn";
    button.textContent = "Add to WorkshopDL";


    Object.assign(button.style, {
        position: "fixed",
        top: "20px",
        right: "20px",
        zIndex: "999999",
        padding: "12px 20px",
        background: "linear-gradient(to right, #47bfff 5%, #1a44c2 60%)",
        color: "white",
        border: "none",
        cursor: "pointer",
        fontSize: "14px",
        fontWeight: "bold",
        borderRadius: "3px",
        boxShadow: "0 4px 6px rgba(0,0,0,0.3)",
        transition: "transform 0.1s"
    });

    button.onmouseover = () => button.style.transform = "scale(1.05)";
    button.onmouseout = () => button.style.transform = "scale(1)";
    button.onclick = addWorkshopItem;

    document.body.appendChild(button);
}

createButton();