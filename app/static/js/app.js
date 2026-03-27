(function () {
    "use strict";

    const App = {
        init() {
            this.initTooltips();
            this.initAutoDismissAlerts();
            this.initConfirmActions();
            this.initActiveSidebarState();
            this.initGlobalSearchShortcuts();
            this.initPWAInstallPrompt();
            this.registerServiceWorker();
        },

        initTooltips() {
            if (typeof bootstrap === "undefined") return;

            const tooltipTriggerList = [].slice.call(
                document.querySelectorAll('[data-bs-toggle="tooltip"]')
            );

            tooltipTriggerList.forEach((tooltipTriggerEl) => {
                new bootstrap.Tooltip(tooltipTriggerEl);
            });
        },

        initAutoDismissAlerts() {
            const alerts = document.querySelectorAll(".alert[data-auto-dismiss='true']");

            alerts.forEach((alertEl) => {
                const delay = parseInt(alertEl.dataset.dismissDelay || "4000", 10);

                window.setTimeout(() => {
                    if (typeof bootstrap !== "undefined") {
                        const alertInstance = bootstrap.Alert.getOrCreateInstance(alertEl);
                        alertInstance.close();
                    } else {
                        alertEl.remove();
                    }
                }, delay);
            });
        },

        initConfirmActions() {
            const confirmButtons = document.querySelectorAll("[data-confirm-message]");

            confirmButtons.forEach((button) => {
                button.addEventListener("click", (event) => {
                    const message = button.getAttribute("data-confirm-message") || "¿Está seguro de continuar?";
                    const confirmed = window.confirm(message);

                    if (!confirmed) {
                        event.preventDefault();
                        event.stopPropagation();
                    }
                });
            });
        },

        initActiveSidebarState() {
            const currentPath = window.location.pathname;
            const sidebarLinks = document.querySelectorAll(".sidebar-link");

            sidebarLinks.forEach((link) => {
                const href = link.getAttribute("href");

                if (!href || href === "#") return;

                if (currentPath === href || (href !== "/" && currentPath.startsWith(href))) {
                    link.classList.add("active");
                } else {
                    link.classList.remove("active");
                }
            });
        },

        initGlobalSearchShortcuts() {
            document.addEventListener("keydown", (event) => {
                // Evita activar shortcuts mientras se escribe en input/textarea/select
                const tagName = (event.target.tagName || "").toLowerCase();
                const isTypingContext = ["input", "textarea", "select"].includes(tagName);

                if (isTypingContext) return;

                // Ctrl + / o Cmd + /
                if ((event.ctrlKey || event.metaKey) && event.key === "/") {
                    event.preventDefault();

                    const searchInput = document.querySelector(
                        "[data-global-search], input[type='search'], input[name='q']"
                    );

                    if (searchInput) {
                        searchInput.focus();
                        searchInput.select?.();
                    }
                }
            });
        },

        initPWAInstallPrompt() {
            let deferredPrompt = null;
            const installButtons = document.querySelectorAll("[data-pwa-install]");

            window.addEventListener("beforeinstallprompt", (event) => {
                event.preventDefault();
                deferredPrompt = event;

                installButtons.forEach((btn) => {
                    btn.classList.remove("d-none");
                    btn.disabled = false;
                });
            });

            installButtons.forEach((btn) => {
                btn.addEventListener("click", async () => {
                    if (!deferredPrompt) return;

                    deferredPrompt.prompt();
                    const choiceResult = await deferredPrompt.userChoice;

                    if (choiceResult.outcome === "accepted") {
                        console.log("PWA instalada por el usuario.");
                    } else {
                        console.log("Instalación PWA cancelada.");
                    }

                    deferredPrompt = null;

                    installButtons.forEach((button) => {
                        button.classList.add("d-none");
                    });
                });
            });

            window.addEventListener("appinstalled", () => {
                console.log("La aplicación fue instalada.");
                installButtons.forEach((btn) => btn.classList.add("d-none"));
            });
        },

        registerServiceWorker() {
            if (!("serviceWorker" in navigator)) return;

            window.addEventListener("load", async () => {
                try {
                    const registration = await navigator.serviceWorker.register("/static/service-worker.js");
                    console.log("Service Worker registrado con éxito:", registration.scope);
                } catch (error) {
                    console.warn("No se pudo registrar el Service Worker:", error);
                }
            });
        },

        notify(message, type = "success", delay = 3500) {
            const containerId = "app-toast-container";
            let container = document.getElementById(containerId);

            if (!container) {
                container = document.createElement("div");
                container.id = containerId;
                container.className = "toast-container position-fixed top-0 end-0 p-3";
                container.style.zIndex = "1080";
                document.body.appendChild(container);
            }

            const toastEl = document.createElement("div");
            toastEl.className = `toast align-items-center text-bg-${type} border-0`;
            toastEl.setAttribute("role", "alert");
            toastEl.setAttribute("aria-live", "assertive");
            toastEl.setAttribute("aria-atomic", "true");

            toastEl.innerHTML = `
                <div class="d-flex">
                    <div class="toast-body">${message}</div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Cerrar"></button>
                </div>
            `;

            container.appendChild(toastEl);

            if (typeof bootstrap !== "undefined") {
                const toast = new bootstrap.Toast(toastEl, { delay });
                toast.show();

                toastEl.addEventListener("hidden.bs.toast", () => {
                    toastEl.remove();
                });
            } else {
                window.setTimeout(() => toastEl.remove(), delay);
            }
        }
    };

    window.App = App;

    document.addEventListener("DOMContentLoaded", () => {
        App.init();
    });
})();