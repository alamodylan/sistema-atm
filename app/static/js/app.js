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
            this.initNotifications();
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
                const tagName = (event.target.tagName || "").toLowerCase();
                const isTypingContext = ["input", "textarea", "select"].includes(tagName);

                if (isTypingContext) return;

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

        initNotifications() {
            if (window.location.pathname.includes("/login")) {
                return;
            }

            const notificationButton = document.getElementById(
                "notificationBellButton"
            );

            const notificationContainer = document.getElementById(
                "notificationDropdownContent"
            );

            const notificationModal = document.getElementById(
                "transferNotificationModal"
            );

            const hasNotificationPanel = Boolean(
                notificationButton || notificationContainer
            );

            const hasPopupNotifications = Boolean(
                notificationModal
            );

            /*
            * Si la página no contiene ni campana/panel ni modal,
            * no se inicializa ninguna consulta de notificaciones.
            */
            if (!hasNotificationPanel && !hasPopupNotifications) {
                return;
            }

            // =====================================================
            // CARGA INICIAL
            // =====================================================

            if (hasNotificationPanel) {
                this.loadNotificationPanel();
            }

            if (hasPopupNotifications) {
                this.checkPopupNotifications();
            }

            // =====================================================
            // MARCAR TODAS COMO LEÍDAS AL ABRIR LA CAMPANA
            // =====================================================

            if (notificationButton) {
                notificationButton.addEventListener("click", () => {
                    this.markAllNotificationsRead();
                });
            }

            // =====================================================
            // RECARGA DEL PANEL
            // Cada tres minutos y solo con la pestaña visible.
            // =====================================================

            if (hasNotificationPanel) {
                window.setInterval(() => {
                    if (document.visibilityState !== "visible") {
                        return;
                    }

                    this.loadNotificationPanel();
                }, 180000);
            }

            // =====================================================
            // VERIFICACIÓN DE POPUPS
            // Cada cinco minutos y solo con la pestaña visible.
            // =====================================================

            if (hasPopupNotifications) {
                window.setInterval(() => {
                    if (document.visibilityState !== "visible") {
                        return;
                    }

                    this.checkPopupNotifications();
                }, 300000);
            }

            // =====================================================
            // ACTUALIZAR AL REGRESAR A UNA PESTAÑA
            // =====================================================

            document.addEventListener("visibilitychange", () => {
                if (document.visibilityState !== "visible") {
                    return;
                }

                if (hasNotificationPanel) {
                    this.loadNotificationPanel();
                }

                if (hasPopupNotifications) {
                    this.checkPopupNotifications();
                }
            });
        },

        async loadNotificationPanel() {
            try {
                const response = await fetch(
                    "/notifications/panel",
                    {
                        cache: "no-store",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    }
                );

                if (!response.ok) {
                    return;
                }

                const data = await response.json();

                const badge = document.getElementById(
                    "notificationUnreadBadge"
                );

                const container = document.getElementById(
                    "notificationDropdownContent"
                );

                if (badge) {
                    const unread = data.unread_count || 0;

                    if (unread > 0) {
                        badge.textContent = unread;
                        badge.classList.remove("d-none");
                    } else {
                        badge.classList.add("d-none");
                    }
                }

                if (!container) {
                    return;
                }

                const items = data.items || [];

                if (!items.length) {
                    container.innerHTML = `
                        <div class="p-3 text-center text-muted small">
                            No hay notificaciones.
                        </div>
                    `;
                    return;
                }

                container.innerHTML = items.map((item) => {
                    const createdAt = item.created_at
                        ? new Date(item.created_at).toLocaleString()
                        : "";

                    const href = item.entity_type === "TRANSFER" && item.entity_id
                        ? `/transfers/transfers/${item.entity_id}`
                        : "#";

                    return `
                        <a
                            href="${href}"
                            class="dropdown-item border-bottom py-3 ${item.is_read ? "" : "bg-light"}"
                            data-notification-id="${item.id}"
                        >
                            <div class="fw-semibold mb-1">
                                ${item.title || ""}
                            </div>

                            <div class="small text-muted mb-1">
                                ${item.message || ""}
                            </div>

                            <div class="small text-secondary">
                                ${createdAt}
                            </div>
                        </a>
                    `;
                }).join("");

                container
                    .querySelectorAll("[data-notification-id]")
                    .forEach((el) => {
                        el.addEventListener("click", () => {
                            const notificationId = el.dataset.notificationId;

                            fetch(
                                `/notifications/${notificationId}/read`,
                                {
                                    method: "POST",
                                    headers: {
                                        "X-Requested-With": "XMLHttpRequest",
                                    },
                                }
                            );
                        });
                    });

            } catch (error) {
                console.warn(
                    "No se pudieron cargar notificaciones:",
                    error
                );
            }
        },

        async checkPopupNotifications() {
            try {
                const response = await fetch(
                    "/notifications/popup-check",
                    {
                        cache: "no-store",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    }
                );

                if (!response.ok) {
                    return;
                }

                const data = await response.json();
                const items = data.items || [];

                if (!items.length) {
                    return;
                }

                const item = items[0];
                this.showTransferPopup(item);

            } catch (error) {
                console.warn(
                    "No se pudieron verificar popups:",
                    error
                );
            }
        },

        async markAllNotificationsRead() {
            try {
                const response = await fetch(
                    "/notifications/mark-all-read",
                    {
                        method: "POST",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    }
                );

                if (!response.ok) {
                    return;
                }

                /*
                * Ocultar el contador localmente.
                * Ya no se hace otra petición GET /notifications/panel.
                */
                const badge = document.getElementById(
                    "notificationUnreadBadge"
                );

                if (badge) {
                    badge.textContent = "0";
                    badge.classList.add("d-none");
                }

                /*
                * Quitar visualmente el fondo de no leído de los elementos
                * ya mostrados en el panel.
                */
                document
                    .querySelectorAll("[data-notification-id]")
                    .forEach((item) => {
                        item.classList.remove("bg-light");
                    });

            } catch (error) {
                console.warn(
                    "No se pudieron marcar notificaciones:",
                    error
                );
            }
        },

        showTransferPopup(item) {
            if (typeof bootstrap === "undefined") {
                return;
            }

            const modalEl = document.getElementById(
                "transferNotificationModal"
            );

            if (!modalEl) {
                return;
            }

            const titleEl = document.getElementById(
                "transferNotificationTitle"
            );

            const messageEl = document.getElementById(
                "transferNotificationMessage"
            );

            const elapsedEl = document.getElementById(
                "transferNotificationElapsed"
            );

            const linkEl = document.getElementById(
                "transferNotificationLink"
            );

            if (titleEl) {
                titleEl.textContent = item.title || "Traslado pendiente";
            }

            if (messageEl) {
                messageEl.textContent = item.message || "";
            }

            if (elapsedEl) {
                const seconds = parseInt(item.elapsed_seconds || 0, 10);
                elapsedEl.textContent = this.formatElapsedTime(seconds);
            }

            if (linkEl && item.transfer_id) {
                linkEl.href = `/transfers/transfers/${item.transfer_id}`;
            }

            const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
            modal.show();
        },

        formatElapsedTime(seconds) {
            if (!seconds || seconds <= 0) {
                return "Hace unos segundos";
            }

            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);

            if (hours <= 0) {
                return `${minutes} min`;
            }

            return `${hours}h ${minutes}m`;
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