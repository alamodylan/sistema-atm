(function () {
    "use strict";

    const Notifications = {
        state: {
            items: [],
            unreadCount: 0,
            pollingIntervalMs: 15000,
            pollingTimer: null,
            endpoint: null,
            enabled: false
        },

        selectors: {
            badge: "[data-notification-badge]",
            list: "[data-notification-list]",
            empty: "[data-notification-empty]",
            refreshButton: "[data-notification-refresh]"
        },

        init(options = {}) {
            this.state.endpoint = options.endpoint || null;
            this.state.pollingIntervalMs = options.pollingIntervalMs || 15000;
            this.state.enabled = Boolean(this.state.endpoint);

            this.cacheDom();
            this.bindEvents();

            if (this.state.enabled) {
                this.fetchNotifications();
                this.startPolling();
            } else {
                console.warn("Notifications: no se configuró endpoint, se inicia en modo manual.");
            }
        },

        cacheDom() {
            this.badge = document.querySelector(this.selectors.badge);
            this.list = document.querySelector(this.selectors.list);
            this.empty = document.querySelector(this.selectors.empty);
            this.refreshButton = document.querySelector(this.selectors.refreshButton);
        },

        bindEvents() {
            this.refreshButton?.addEventListener("click", () => {
                this.fetchNotifications(true);
            });
        },

        async fetchNotifications(showToast = false) {
            if (!this.state.endpoint) return;

            try {
                const response = await fetch(this.state.endpoint, {
                    method: "GET",
                    headers: {
                        "Content-Type": "application/json"
                    }
                });

                if (!response.ok) {
                    throw new Error(`Error HTTP ${response.status}`);
                }

                const data = await response.json();

                this.state.items = Array.isArray(data.items) ? data.items : [];
                this.state.unreadCount = Number(data.unread_count || 0);

                this.renderBadge();
                this.renderList();

                if (showToast) {
                    this.notify("Notificaciones actualizadas.", "info");
                }
            } catch (error) {
                console.error("Notifications.fetchNotifications:", error);
                if (showToast) {
                    this.notify("No se pudieron actualizar las notificaciones.", "danger");
                }
            }
        },

        renderBadge() {
            if (!this.badge) return;

            const count = this.state.unreadCount;

            if (count <= 0) {
                this.badge.textContent = "0";
                this.badge.classList.add("d-none");
                return;
            }

            this.badge.textContent = count > 99 ? "99+" : String(count);
            this.badge.classList.remove("d-none");
        },

        renderList() {
            if (!this.list) return;

            if (!this.state.items.length) {
                this.list.innerHTML = "";
                this.showEmptyState(true);
                return;
            }

            this.showEmptyState(false);

            this.list.innerHTML = this.state.items
                .map((item) => this.renderNotificationItem(item))
                .join("");

            this.bindNotificationActions();
        },

        renderNotificationItem(item) {
            const title = this.escapeHtml(item.title || "Notificación");
            const message = this.escapeHtml(item.message || "");
            const createdAt = this.escapeHtml(item.created_at || "");
            const type = this.escapeHtml(item.type || "info");
            const link = item.link || "#";
            const id = item.id || "";

            const badgeClass = this.getTypeBadgeClass(type);
            const unreadClass = item.is_read ? "" : "notification-unread";

            return `
                <div class="notification-item border rounded-4 p-3 mb-2 bg-white shadow-sm ${unreadClass}" data-notification-id="${id}">
                    <div class="d-flex justify-content-between align-items-start gap-3">
                        <div class="flex-grow-1">
                            <div class="d-flex align-items-center gap-2 mb-1">
                                <span class="badge ${badgeClass}">${type.toUpperCase()}</span>
                                <span class="small text-secondary">${createdAt}</span>
                            </div>
                            <div class="fw-bold text-dark">${title}</div>
                            <div class="text-secondary small mt-1">${message}</div>
                        </div>

                        <div class="dropdown">
                            <button class="btn btn-sm btn-light border" data-bs-toggle="dropdown" aria-expanded="false">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end shadow-sm border-0">
                                <li>
                                    <a class="dropdown-item" href="${link}">
                                        <i class="bi bi-box-arrow-up-right me-2"></i>Ver detalle
                                    </a>
                                </li>
                                <li>
                                    <button class="dropdown-item notification-mark-read-btn" data-id="${id}">
                                        <i class="bi bi-check2-circle me-2"></i>Marcar como leída
                                    </button>
                                </li>
                            </ul>
                        </div>
                    </div>
                </div>
            `;
        },

        bindNotificationActions() {
            const buttons = document.querySelectorAll(".notification-mark-read-btn");

            buttons.forEach((button) => {
                button.addEventListener("click", async () => {
                    const id = button.dataset.id;
                    await this.markAsRead(id);
                });
            });
        },

        async markAsRead(notificationId) {
            if (!notificationId) return;

            const item = this.state.items.find((n) => String(n.id) === String(notificationId));
            if (!item || item.is_read) return;

            try {
                // Aquí después conectas el endpoint real de marcar leída
                item.is_read = true;

                if (this.state.unreadCount > 0) {
                    this.state.unreadCount -= 1;
                }

                this.renderBadge();
                this.renderList();

                this.notify("Notificación marcada como leída.", "success");
            } catch (error) {
                console.error("Notifications.markAsRead:", error);
                this.notify("No se pudo marcar la notificación como leída.", "danger");
            }
        },

        showEmptyState(show) {
            if (!this.empty) return;

            if (show) {
                this.empty.classList.remove("d-none");
            } else {
                this.empty.classList.add("d-none");
            }
        },

        startPolling() {
            this.stopPolling();

            this.state.pollingTimer = window.setInterval(() => {
                this.fetchNotifications(false);
            }, this.state.pollingIntervalMs);
        },

        stopPolling() {
            if (this.state.pollingTimer) {
                clearInterval(this.state.pollingTimer);
                this.state.pollingTimer = null;
            }
        },

        push(notification) {
            this.state.items.unshift({
                id: notification.id || `tmp-${Date.now()}`,
                title: notification.title || "Nueva notificación",
                message: notification.message || "",
                created_at: notification.created_at || "Ahora",
                type: notification.type || "info",
                link: notification.link || "#",
                is_read: false
            });

            this.state.unreadCount += 1;
            this.renderBadge();
            this.renderList();

            this.notify(notification.title || "Nueva notificación", notification.toastType || "info");
        },

        getTypeBadgeClass(type) {
            switch ((type || "").toLowerCase()) {
                case "success":
                    return "text-bg-success";
                case "warning":
                    return "text-bg-warning";
                case "danger":
                case "error":
                    return "text-bg-danger";
                case "transfer":
                    return "text-bg-info";
                case "audit":
                    return "text-bg-dark";
                default:
                    return "text-bg-secondary";
            }
        },

        escapeHtml(value) {
            return String(value)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        },

        notify(message, type = "success") {
            if (window.App && typeof window.App.notify === "function") {
                window.App.notify(message, type);
            } else {
                console.log(`[${type}] ${message}`);
            }
        }
    };

    window.Notifications = Notifications;
})();