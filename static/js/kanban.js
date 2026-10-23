(() => {
    const board = document.querySelector("[data-kanban-board]");
    if (!board || board.dataset.canMove !== "true") return;

    const status = document.querySelector("[data-kanban-status]");
    let drag = null;
    let saving = false;
    let reloadPending = false;

    const csrfToken = () => {
        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    };

    const setStatus = (message, isError = false) => {
        status.textContent = message;
        status.classList.toggle("is-error", isError);
    };

    const updateEmptyStates = () => {
        board.querySelectorAll("[data-task-list]").forEach((list) => {
            const empty = list.querySelector("[data-empty-state]");
            const hasCards = list.querySelector("[data-task-id]");
            if (empty) empty.hidden = Boolean(hasCards);
        });
    };

    const restorePosition = (operation) => {
        operation.parent.insertBefore(operation.card, operation.next);
        updateEmptyStates();
    };

    board.addEventListener("dragstart", (event) => {
        const card = event.target.closest("[data-task-id]");
        if (!card || card.draggable !== true) return;
        if (saving || reloadPending) {
            event.preventDefault();
            return;
        }
        drag = {card, parent: card.parentNode, next: card.nextSibling, dropped: false};
        card.classList.add("is-dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.dataset.taskId);
    });

    board.addEventListener("dragover", (event) => {
        const list = event.target.closest("[data-task-list]");
        if (!list || !drag || drag.dropped) return;
        event.preventDefault();
        const cards = [...list.querySelectorAll("[data-task-id]:not(.is-dragging)")];
        const next = cards.find((card) => event.clientY < card.getBoundingClientRect().top + card.offsetHeight / 2);
        list.insertBefore(drag.card, next || null);
        updateEmptyStates();
    });

    board.addEventListener("drop", async (event) => {
        const list = event.target.closest("[data-task-list]");
        if (!list || !drag || drag.dropped) return;
        event.preventDefault();
        // dragend can fire while fetch is pending. Retain this operation's
        // original position independently of the current drag state.
        const operation = drag;
        operation.dropped = true;
        saving = true;
        const position = [...list.querySelectorAll("[data-task-id]")].indexOf(operation.card);
        setStatus("در حال ذخیرهٔ جایگاه جدید…");
        try {
            const response = await fetch(operation.card.dataset.moveUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken()},
                body: JSON.stringify({column: Number(list.dataset.columnId), position}),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "ذخیرهٔ جابه‌جایی انجام نشد.");
            setStatus("جایگاه وظیفه ذخیره شد.");
        } catch (error) {
            restorePosition(operation);
            setStatus("ذخیرهٔ جابه‌جایی انجام نشد. وضعیت برد دوباره دریافت می‌شود.", true);
            // A lost response may follow a committed write; refresh to obtain
            // the authoritative server order after restoring the last known one.
            reloadPending = true;
            window.setTimeout(() => window.location.reload(), 900);
        } finally {
            saving = false;
        }
    });

    board.addEventListener("dragend", () => {
        if (drag) {
            drag.card.classList.remove("is-dragging");
            if (!drag.dropped) restorePosition(drag);
        }
        drag = null;
    });
})();
