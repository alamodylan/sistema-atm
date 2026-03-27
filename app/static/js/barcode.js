(function () {
    "use strict";

    const Barcode = {
        activeListeners: new Map(),

        initAutoFocusInputs() {
            const inputs = document.querySelectorAll("[data-barcode-autofocus]");

            inputs.forEach((input) => {
                this.attachPersistentFocus(input);
            });
        },

        attachPersistentFocus(input) {
            if (!input) return;

            const keepFocus = () => {
                if (document.activeElement !== input) {
                    input.focus();
                }
            };

            // Recupera foco al cargar
            window.setTimeout(keepFocus, 150);

            // Recupera foco al hacer clic afuera
            document.addEventListener("click", (event) => {
                const clickedInside = input.contains(event.target) || event.target === input;
                if (!clickedInside) {
                    window.setTimeout(keepFocus, 80);
                }
            });

            // Recupera foco si se pierde
            input.addEventListener("blur", () => {
                window.setTimeout(keepFocus, 80);
            });
        },

        bindScanInput({
            selector,
            onScan,
            minLength = 1,
            clearAfterScan = true,
            focusAfterScan = true,
            trim = true
        }) {
            const input = document.querySelector(selector);
            if (!input) {
                console.warn(`Barcode.bindScanInput: no se encontró el selector ${selector}`);
                return;
            }

            const handler = (event) => {
                if (event.key !== "Enter") return;

                event.preventDefault();

                let value = input.value;
                if (trim) value = value.trim();

                if (!value || value.length < minLength) {
                    this.notify("Código escaneado inválido o incompleto.", "warning");
                    if (clearAfterScan) input.value = "";
                    if (focusAfterScan) input.focus();
                    return;
                }

                try {
                    onScan(value, input);
                } catch (error) {
                    console.error("Error procesando escaneo:", error);
                    this.notify("Ocurrió un error al procesar el escaneo.", "danger");
                }

                if (clearAfterScan) {
                    input.value = "";
                }

                if (focusAfterScan) {
                    window.setTimeout(() => input.focus(), 50);
                }
            };

            input.addEventListener("keydown", handler);
            this.activeListeners.set(selector, { input, handler });

            if (input.hasAttribute("data-barcode-autofocus")) {
                this.attachPersistentFocus(input);
            }

            return input;
        },

        unbindScanInput(selector) {
            const listenerData = this.activeListeners.get(selector);
            if (!listenerData) return;

            listenerData.input.removeEventListener("keydown", listenerData.handler);
            this.activeListeners.delete(selector);
        },

        readValue(inputOrSelector, trim = true) {
            const input =
                typeof inputOrSelector === "string"
                    ? document.querySelector(inputOrSelector)
                    : inputOrSelector;

            if (!input) return "";

            const value = input.value || "";
            return trim ? value.trim() : value;
        },

        clearInput(inputOrSelector, focus = false) {
            const input =
                typeof inputOrSelector === "string"
                    ? document.querySelector(inputOrSelector)
                    : inputOrSelector;

            if (!input) return;

            input.value = "";

            if (focus) {
                window.setTimeout(() => input.focus(), 50);
            }
        },

        disableInput(inputOrSelector) {
            const input =
                typeof inputOrSelector === "string"
                    ? document.querySelector(inputOrSelector)
                    : inputOrSelector;

            if (!input) return;
            input.disabled = true;
        },

        enableInput(inputOrSelector, focus = false) {
            const input =
                typeof inputOrSelector === "string"
                    ? document.querySelector(inputOrSelector)
                    : inputOrSelector;

            if (!input) return;
            input.disabled = false;

            if (focus) {
                window.setTimeout(() => input.focus(), 50);
            }
        },

        injectValue(inputOrSelector, value, triggerEnter = false) {
            const input =
                typeof inputOrSelector === "string"
                    ? document.querySelector(inputOrSelector)
                    : inputOrSelector;

            if (!input) return;

            input.value = value;

            if (triggerEnter) {
                const event = new KeyboardEvent("keydown", {
                    key: "Enter",
                    bubbles: true
                });
                input.dispatchEvent(event);
            }
        },

        notify(message, type = "success") {
            if (window.App && typeof window.App.notify === "function") {
                window.App.notify(message, type);
            } else {
                console.log(`[${type}] ${message}`);
            }
        }
    };

    window.Barcode = Barcode;

    document.addEventListener("DOMContentLoaded", () => {
        Barcode.initAutoFocusInputs();
    });
})();