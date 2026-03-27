(function () {
    "use strict";

    const WorkshopTouch = {
        state: {
            currentMechanic: null,
            currentWorkOrder: null,
            requestedItems: [],
            mechanicBarcode: "",
            searchResults: [],
            workOrders: []
        },

        selectors: {
            waitingScreen: "[data-wt-waiting-screen]",
            mechanicScreen: "[data-wt-mechanic-screen]",
            workOrdersContainer: "[data-wt-workorders]",
            articleSearchInput: "[data-wt-article-search]",
            articleResultsContainer: "[data-wt-article-results]",
            requestedItemsContainer: "[data-wt-requested-items]",
            barcodeInput: "[data-wt-barcode-input]",
            mechanicName: "[data-wt-mechanic-name]",
            currentOtNumber: "[data-wt-current-ot-number]",
            resetButton: "[data-wt-reset]",
            confirmRequestButton: "[data-wt-confirm-request]",
            backToOrdersButton: "[data-wt-back-orders]"
        },

        init() {
            this.cacheDom();
            if (!this.barcodeInput) return;

            this.bindEvents();
            this.resetToWaitingState();
        },

        cacheDom() {
            this.waitingScreen = document.querySelector(this.selectors.waitingScreen);
            this.mechanicScreen = document.querySelector(this.selectors.mechanicScreen);
            this.workOrdersContainer = document.querySelector(this.selectors.workOrdersContainer);
            this.articleSearchInput = document.querySelector(this.selectors.articleSearchInput);
            this.articleResultsContainer = document.querySelector(this.selectors.articleResultsContainer);
            this.requestedItemsContainer = document.querySelector(this.selectors.requestedItemsContainer);
            this.barcodeInput = document.querySelector(this.selectors.barcodeInput);
            this.mechanicName = document.querySelector(this.selectors.mechanicName);
            this.currentOtNumber = document.querySelector(this.selectors.currentOtNumber);
            this.resetButton = document.querySelector(this.selectors.resetButton);
            this.confirmRequestButton = document.querySelector(this.selectors.confirmRequestButton);
            this.backToOrdersButton = document.querySelector(this.selectors.backToOrdersButton);
        },

        bindEvents() {
            this.barcodeInput.addEventListener("change", () => {
                const barcode = this.barcodeInput.value.trim();
                if (!barcode) return;

                this.handleMechanicScan(barcode);
            });

            this.articleSearchInput?.addEventListener("input", (event) => {
                const query = event.target.value.trim();
                this.handleArticleSearch(query);
            });

            this.resetButton?.addEventListener("click", () => {
                this.resetToWaitingState();
            });

            this.confirmRequestButton?.addEventListener("click", () => {
                this.confirmRequest();
            });

            this.backToOrdersButton?.addEventListener("click", () => {
                this.clearCurrentWorkOrderSelection();
            });

            document.addEventListener("keydown", (event) => {
                if (event.key === "Escape") {
                    this.resetToWaitingState();
                }
            });
        },

        resetToWaitingState() {
            this.state.currentMechanic = null;
            this.state.currentWorkOrder = null;
            this.state.requestedItems = [];
            this.state.workOrders = [];
            this.state.searchResults = [];

            this.clearBarcodeInput();
            this.clearArticleSearch();
            this.clearResults();
            this.renderRequestedItems();
            this.renderWorkOrders();

            this.setText(this.mechanicName, "Esperando mecánico...");
            this.setText(this.currentOtNumber, "Sin OT seleccionada");

            this.showElement(this.waitingScreen);
            this.hideElement(this.mechanicScreen);

            this.focusBarcodeInput();
        },

        async handleMechanicScan(barcode) {
            try {
                // Aquí luego cambiarás esto por fetch real al backend
                const mechanicData = await this.mockFetchMechanicByBarcode(barcode);

                if (!mechanicData) {
                    this.notify("No se encontró un mecánico con ese código.", "danger");
                    this.clearBarcodeInput();
                    this.focusBarcodeInput();
                    return;
                }

                this.state.currentMechanic = mechanicData.mechanic;
                this.state.workOrders = mechanicData.work_orders || [];

                this.setText(this.mechanicName, mechanicData.mechanic.full_name);
                this.renderWorkOrders();

                this.hideElement(this.waitingScreen);
                this.showElement(this.mechanicScreen);

                this.notify(`Mecánico identificado: ${mechanicData.mechanic.full_name}`, "success");
                this.clearBarcodeInput();
            } catch (error) {
                console.error(error);
                this.notify("No se pudo procesar el escaneo del mecánico.", "danger");
            }
        },

        async handleArticleSearch(query) {
            if (!this.state.currentWorkOrder) {
                this.renderArticleResultsMessage("Primero seleccione una OT.");
                return;
            }

            if (!query || query.length < 2) {
                this.renderArticleResultsMessage("Digite al menos 2 caracteres para buscar.");
                return;
            }

            try {
                // Luego esto se cambia por fetch real
                const results = await this.mockSearchArticles(query);
                this.state.searchResults = results;
                this.renderArticleResults();
            } catch (error) {
                console.error(error);
                this.renderArticleResultsMessage("No se pudieron cargar los artículos.");
            }
        },

        selectWorkOrder(workOrder) {
            this.state.currentWorkOrder = workOrder;
            this.setText(this.currentOtNumber, workOrder.number);
            this.clearArticleSearch();
            this.clearResults();
            this.notify(`OT seleccionada: ${workOrder.number}`, "info");
            this.articleSearchInput?.focus();
        },

        clearCurrentWorkOrderSelection() {
            this.state.currentWorkOrder = null;
            this.state.searchResults = [];
            this.clearArticleSearch();
            this.clearResults();
            this.setText(this.currentOtNumber, "Sin OT seleccionada");
            this.notify("Selección de OT limpiada.", "secondary");
        },

        addArticleToRequest(article) {
            if (!this.state.currentWorkOrder) {
                this.notify("Debe seleccionar una OT antes de agregar artículos.", "warning");
                return;
            }

            const existing = this.state.requestedItems.find(
                (item) => item.article_id === article.article_id
            );

            if (existing) {
                existing.quantity_requested += 1;
            } else {
                this.state.requestedItems.push({
                    article_id: article.article_id,
                    code: article.code,
                    name: article.name,
                    quantity_requested: 1
                });
            }

            this.renderRequestedItems();
            this.notify(`${article.name} agregado a la solicitud.`, "success");
            this.clearArticleSearch();
            this.clearResults();
            this.articleSearchInput?.focus();
        },

        removeRequestedItem(articleId) {
            this.state.requestedItems = this.state.requestedItems.filter(
                (item) => item.article_id !== articleId
            );

            this.renderRequestedItems();
            this.notify("Artículo removido de la solicitud.", "warning");
        },

        updateRequestedItemQuantity(articleId, value) {
            const item = this.state.requestedItems.find((row) => row.article_id === articleId);
            if (!item) return;

            const quantity = parseInt(value, 10);

            if (Number.isNaN(quantity) || quantity <= 0) {
                item.quantity_requested = 1;
            } else {
                item.quantity_requested = quantity;
            }

            this.renderRequestedItems();
        },

        async confirmRequest() {
            if (!this.state.currentMechanic) {
                this.notify("Debe escanear un mecánico.", "warning");
                return;
            }

            if (!this.state.currentWorkOrder) {
                this.notify("Debe seleccionar una OT.", "warning");
                return;
            }

            if (!this.state.requestedItems.length) {
                this.notify("Debe agregar al menos un artículo a la solicitud.", "warning");
                return;
            }

            try {
                const payload = {
                    mechanic_id: this.state.currentMechanic.id,
                    work_order_id: this.state.currentWorkOrder.id,
                    items: this.state.requestedItems
                };

                console.log("Solicitud a enviar:", payload);

                // Aquí luego va el fetch real al backend
                await this.mockSubmitRequest(payload);

                this.notify("Solicitud registrada correctamente.", "success");

                this.state.requestedItems = [];
                this.renderRequestedItems();
                this.clearCurrentWorkOrderSelection();

                setTimeout(() => {
                    this.resetToWaitingState();
                }, 1000);
            } catch (error) {
                console.error(error);
                this.notify("No se pudo registrar la solicitud.", "danger");
            }
        },

        renderWorkOrders() {
            if (!this.workOrdersContainer) return;

            if (!this.state.workOrders.length) {
                this.workOrdersContainer.innerHTML = `
                    <div class="text-center text-secondary py-4">
                        No hay órdenes de trabajo disponibles para este mecánico.
                    </div>
                `;
                return;
            }

            this.workOrdersContainer.innerHTML = this.state.workOrders
                .map((wo) => {
                    return `
                        <button type="button"
                                class="btn btn-light border rounded-4 w-100 text-start p-3 mb-2 shadow-sm wt-workorder-btn"
                                data-workorder-id="${wo.id}">
                            <div class="fw-bold">${wo.number}</div>
                            <div class="small text-secondary">Equipo: ${wo.equipment_code || "Sin equipo"}</div>
                            <div class="small text-secondary">Predio: ${wo.site_name}</div>
                        </button>
                    `;
                })
                .join("");

            this.workOrdersContainer
                .querySelectorAll(".wt-workorder-btn")
                .forEach((button) => {
                    button.addEventListener("click", () => {
                        const workOrderId = parseInt(button.dataset.workorderId, 10);
                        const workOrder = this.state.workOrders.find((wo) => wo.id === workOrderId);
                        if (workOrder) this.selectWorkOrder(workOrder);
                    });
                });
        },

        renderArticleResults() {
            if (!this.articleResultsContainer) return;

            if (!this.state.searchResults.length) {
                this.renderArticleResultsMessage("No se encontraron artículos con existencia.");
                return;
            }

            this.articleResultsContainer.innerHTML = this.state.searchResults
                .map((article) => {
                    return `
                        <button type="button"
                                class="btn btn-white border rounded-4 w-100 text-start p-3 mb-2 shadow-sm wt-article-btn"
                                data-article-id="${article.article_id}">
                            <div class="fw-bold">${article.name}</div>
                            <div class="small text-secondary">Código: ${article.code}</div>
                        </button>
                    `;
                })
                .join("");

            this.articleResultsContainer
                .querySelectorAll(".wt-article-btn")
                .forEach((button) => {
                    button.addEventListener("click", () => {
                        const articleId = parseInt(button.dataset.articleId, 10);
                        const article = this.state.searchResults.find((a) => a.article_id === articleId);
                        if (article) this.addArticleToRequest(article);
                    });
                });
        },

        renderArticleResultsMessage(message) {
            if (!this.articleResultsContainer) return;

            this.articleResultsContainer.innerHTML = `
                <div class="border rounded-4 bg-light-subtle text-secondary p-3 text-center">
                    ${message}
                </div>
            `;
        },

        renderRequestedItems() {
            if (!this.requestedItemsContainer) return;

            if (!this.state.requestedItems.length) {
                this.requestedItemsContainer.innerHTML = `
                    <div class="border rounded-4 bg-light-subtle text-secondary p-3 text-center">
                        No hay artículos agregados en esta solicitud.
                    </div>
                `;
                return;
            }

            this.requestedItemsContainer.innerHTML = this.state.requestedItems
                .map((item) => {
                    return `
                        <div class="border rounded-4 p-3 mb-2 bg-white shadow-sm">
                            <div class="d-flex justify-content-between align-items-start gap-3">
                                <div>
                                    <div class="fw-bold">${item.name}</div>
                                    <div class="small text-secondary">Código: ${item.code}</div>
                                </div>
                                <button type="button"
                                        class="btn btn-sm btn-outline-danger wt-remove-item-btn"
                                        data-article-id="${item.article_id}">
                                    <i class="bi bi-x-lg"></i>
                                </button>
                            </div>

                            <div class="mt-3">
                                <label class="form-label small fw-semibold">Cantidad solicitada</label>
                                <input type="number"
                                       min="1"
                                       class="form-control wt-qty-input"
                                       value="${item.quantity_requested}"
                                       data-article-id="${item.article_id}">
                            </div>
                        </div>
                    `;
                })
                .join("");

            this.requestedItemsContainer
                .querySelectorAll(".wt-remove-item-btn")
                .forEach((button) => {
                    button.addEventListener("click", () => {
                        const articleId = parseInt(button.dataset.articleId, 10);
                        this.removeRequestedItem(articleId);
                    });
                });

            this.requestedItemsContainer
                .querySelectorAll(".wt-qty-input")
                .forEach((input) => {
                    input.addEventListener("change", () => {
                        const articleId = parseInt(input.dataset.articleId, 10);
                        this.updateRequestedItemQuantity(articleId, input.value);
                    });
                });
        },

        clearBarcodeInput() {
            if (this.barcodeInput) {
                this.barcodeInput.value = "";
            }
        },

        focusBarcodeInput() {
            if (this.barcodeInput) {
                this.barcodeInput.focus();
            }
        },

        clearArticleSearch() {
            if (this.articleSearchInput) {
                this.articleSearchInput.value = "";
            }
        },

        clearResults() {
            if (this.articleResultsContainer) {
                this.articleResultsContainer.innerHTML = "";
            }
        },

        setText(element, value) {
            if (element) {
                element.textContent = value;
            }
        },

        showElement(element) {
            if (element) element.classList.remove("d-none");
        },

        hideElement(element) {
            if (element) element.classList.add("d-none");
        },

        notify(message, type = "success") {
            if (window.App && typeof window.App.notify === "function") {
                window.App.notify(message, type);
            } else {
                console.log(`[${type}] ${message}`);
            }
        },

        // =====================================================
        // MOCKS TEMPORALES
        // Cambiar después por fetch reales al backend
        // =====================================================

        async mockFetchMechanicByBarcode(barcode) {
            const mechanics = {
                "MEC001": {
                    mechanic: {
                        id: 10,
                        full_name: "Juan Pérez",
                        barcode: "MEC001"
                    },
                    work_orders: [
                        {
                            id: 1,
                            number: "OT-00001",
                            equipment_code: "40112",
                            site_name: "Coyol"
                        },
                        {
                            id: 2,
                            number: "OT-00007",
                            equipment_code: "20123",
                            site_name: "Coyol"
                        }
                    ]
                },
                "MEC002": {
                    mechanic: {
                        id: 11,
                        full_name: "Carlos Vargas",
                        barcode: "MEC002"
                    },
                    work_orders: [
                        {
                            id: 3,
                            number: "OT-00002",
                            equipment_code: "43045",
                            site_name: "Caldera"
                        }
                    ]
                }
            };

            return new Promise((resolve) => {
                setTimeout(() => resolve(mechanics[barcode] || null), 300);
            });
        },

        async mockSearchArticles(query) {
            const allArticles = [
                { article_id: 1, code: "10001", name: "Tornillo 5/8" },
                { article_id: 2, code: "10002", name: "Tornillo galvanizado" },
                { article_id: 3, code: "11025", name: "Lámpara LED" },
                { article_id: 4, code: "19001", name: "Llave ajustable" },
                { article_id: 5, code: "12003", name: "Torquímetro" }
            ];

            return new Promise((resolve) => {
                const q = query.toLowerCase();
                const filtered = allArticles.filter((article) =>
                    article.name.toLowerCase().includes(q) ||
                    article.code.toLowerCase().includes(q)
                );

                setTimeout(() => resolve(filtered), 200);
            });
        },

        async mockSubmitRequest(payload) {
            return new Promise((resolve) => {
                console.log("Solicitud enviada (mock):", payload);
                setTimeout(() => resolve({ ok: true }), 500);
            });
        }
    };

    window.WorkshopTouch = WorkshopTouch;

    document.addEventListener("DOMContentLoaded", () => {
        WorkshopTouch.init();
    });
})();