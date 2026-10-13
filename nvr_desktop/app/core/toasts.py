"""ToastBus: app-wide notifications (the desktop equivalent of sonner toasts). QML singleton `Toasts`."""

from PySide6.QtCore import QObject, Signal, Slot


class ToastBus(QObject):
    toast = Signal(str, str)  # (kind: success | error | info, message)

    @Slot(str)
    def success(self, message: str) -> None:
        self.toast.emit("success", message)

    @Slot(str)
    def error(self, message: str) -> None:
        self.toast.emit("error", message)

    @Slot(str)
    def info(self, message: str) -> None:
        self.toast.emit("info", message)
