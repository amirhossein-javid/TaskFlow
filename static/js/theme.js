(() => {
    "use strict";

    const storageKey = "taskflow-theme";
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const root = document.documentElement;
    const menu = document.querySelector("[data-theme-menu]");
    const themeButtons = document.querySelectorAll("[data-theme-value]");
    const themeLabel = document.querySelector("[data-theme-label]");
    const themeColor = document.querySelector('meta[name="theme-color"]');
    const labels = { light: "روشن", dark: "تاریک", system: "سیستم" };

    function getPreference() {
        const preference = root.dataset.themePreference;
        return ["light", "dark", "system"].includes(preference) ? preference : "system";
    }

    function applyTheme(preference, persist = true) {
        const dark = preference === "dark" || (preference === "system" && mediaQuery.matches);
        const resolvedTheme = dark ? "dark" : "light";

        root.dataset.theme = resolvedTheme;
        root.dataset.themePreference = preference;
        root.style.colorScheme = resolvedTheme;
        if (themeColor) {
            themeColor.content = dark ? "#0b0c12" : "#f7f7fb";
        }
        if (themeLabel) {
            themeLabel.textContent = labels[preference];
        }
        themeButtons.forEach((button) => {
            const selected = button.dataset.themeValue === preference;
            button.setAttribute("aria-pressed", String(selected));
        });

        if (persist) {
            try {
                localStorage.setItem(storageKey, preference);
            } catch (error) {
                // The selected theme still applies when storage is unavailable.
            }
        }
    }

    themeButtons.forEach((button) => {
        button.addEventListener("click", () => {
            applyTheme(button.dataset.themeValue);
            if (menu) {
                menu.open = false;
            }
        });
    });

    mediaQuery.addEventListener("change", () => {
        if (getPreference() === "system") {
            applyTheme("system", false);
        }
    });

    document.addEventListener("click", (event) => {
        if (menu?.open && !menu.contains(event.target)) {
            menu.open = false;
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && menu?.open) {
            menu.open = false;
            menu.querySelector("summary")?.focus();
        }
    });

    applyTheme(getPreference(), false);
})();
