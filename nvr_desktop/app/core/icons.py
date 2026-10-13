"""Icon image provider: renders the bundled Lucide SVGs (assets/icons) in any colour.

QML: Image { source: "image://icon/camera/88c0d0" }  (name / hex colour without '#')
The ui/components/Icon.qml component wraps this, so pages just write  Icon { name: "camera" }.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

logger = logging.getLogger(__name__)

ICON_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"


@lru_cache(maxsize=None)
def _svg_source(name: str) -> str | None:
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        logger.warning("Missing icon: %s", name)
        return None
    return path.read_text(encoding="utf-8")


class IconProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, icon_id: str, size: QSize, requested: QSize) -> QImage:
        name, _, color = icon_id.partition("/")
        width = requested.width() if requested.width() > 0 else 24
        height = requested.height() if requested.height() > 0 else width
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        svg = _svg_source(name)
        if svg is not None:
            colour = "#" + (color[-6:] if color else "eceff4")
            renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", colour).encode()))
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter)
            painter.end()
        if size is not None:
            size.setWidth(width)
            size.setHeight(height)
        return image
