(() => {
    const board = document.querySelector("[data-kanban-board]");
    if (!board) return;

    const status = document.querySelector("[data-kanban-status]");
    let draggedCard = null;

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

    board.addEventListener("dragstart", (event) => {
        const card = event.target.closest("[data-task-id]");
        if (!card) return;
        draggedCard = card;
        card.classList.add("is-dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.dataset.taskId);
    });

    board.addEventListener("dragover", (event) => {
        const list = event.target.closest("[data-task-list]");
        if (!list || !draggedCard) return;
        event.preventDefault();
        const cards = [...list.querySelectorAll("[data-task-id]:not(.is-dragging)")];
        const next = cards.find((card) => event.clientY < card.getBoundingClientRect().top + card.offsetHeight / 2);
        list.insertBefore(draggedCard, next || null);
        updateEmptyStates();
    });

    board.addEventListener("drop", async (event) => {
        const list = event.target.closest("[data-task-list]");
        if (!list || !draggedCard) return;
        event.preventDefault();
        const position = [...list.querySelectorAll("[data-task-id]")].indexOf(draggedCard);
        setStatus("در حال ذخیرهٔ جایگاه جدید…");
        try {
            const response = await fetch(draggedCard.dataset.moveUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken()},
                body: JSON.stringify({column: Number(list.dataset.columnId), position}),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "ذخیرهٔ جابه‌جایی انجام نشد.");
            setStatus("جایگاه وظیفه ذخیره شد.");
        } catch (error) {
            setStatus(error.message, true);
            window.setTimeout(() => window.location.reload(), 900);
        }
    });

    board.addEventListener("dragend", () => {
        if (draggedCard) draggedCard.classList.remove("is-dragging");
        draggedCard = null;
    });
})();
