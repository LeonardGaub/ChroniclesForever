"""Motion in the main window, short and calm (option "ui_motion", on by default):

- PageFader: a page change crossfades: the old page's picture lies over the new one and fades out.
- HoverGlow: buttons, the tabs and clickable cards get a soft gold glow that eases in under the mouse and out
  again (a drop shadow in gold, switched on only while it shows). Installed once on the application; only widgets
  of the main window glow (the cinematic mode keeps its own look).
- Toast: an achievement-style alert sliding in at the top right of the page area and fading out after a few
  seconds; the main window shows one after an import that brought new moments (ToastQueue: one after another).
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QLabel, QPushButton, QWidget

from . import theme

FADE_MS = 200
GLOW_MS = 180
GLOW_RADIUS = 22
TOAST_MS = 5200
SLIDE_MS = 380


def enabled(config) -> bool:
    return config.extra.get("ui_motion", True) is not False


class PageFader(QObject):
    """Crossfades a QStackedWidget's page changes: call fade() just before switching."""

    def __init__(self, stack: QWidget, config):
        super().__init__(stack)
        self.stack, self.config = stack, config
        self.cover = QLabel(stack)
        self.cover.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.cover.hide()
        self.effect = QGraphicsOpacityEffect(self.cover)
        self.cover.setGraphicsEffect(self.effect)
        self.animation = QPropertyAnimation(self.effect, b"opacity", self)
        self.animation.setDuration(FADE_MS)
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self.cover.hide)

    def fade(self) -> None:
        if not enabled(self.config) or not self.stack.isVisible() or self.stack.currentWidget() is None:
            return
        self.cover.setPixmap(self.stack.grab())
        self.cover.setGeometry(self.stack.rect())
        self.cover.show()
        self.cover.raise_()
        self.animation.stop()
        self.animation.start()

    @property
    def running(self) -> bool:
        return self.animation.state() == QPropertyAnimation.State.Running


class HoverGlow(QObject):
    """A gold glow easing in under the mouse on buttons, tabs and clickable cards of the given window."""

    def __init__(self, window: QWidget, config):
        super().__init__(window)
        self.window, self.config = window, config
        self.animations: dict[QWidget, QVariantAnimation] = {}
        QApplication.instance().installEventFilter(self)

    def wants(self, widget) -> bool:
        if not isinstance(widget, QWidget) or not widget.isEnabled() or widget.window() is not self.window:
            return False
        if isinstance(widget, QPushButton):
            return widget.objectName() != "Star"
        return widget.objectName() == "Card" and bool(widget.property("clickable"))

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.Enter, QEvent.Type.Leave) and self.wants(obj):
            self.glow(obj, kind == QEvent.Type.Enter)
        return False

    def glow(self, widget: QWidget, on: bool) -> None:
        if not enabled(self.config):
            return
        effect = widget.graphicsEffect()
        if effect is None:
            effect = QGraphicsDropShadowEffect(widget)
            effect.setOffset(0, 0)
            effect.setBlurRadius(0)
            effect.setColor(QColor(255, 209, 0, 0))
            effect.setProperty("hover_glow", True)
            widget.setGraphicsEffect(effect)
        elif not effect.property("hover_glow"):
            return                                  # the widget has an effect of its own
        effect.setEnabled(True)
        animation = self.animations.get(widget)
        start = animation.currentValue() if animation is not None else 0.0
        if animation is not None:
            animation.stop()
        animation = QVariantAnimation(self)
        animation.setDuration(GLOW_MS)
        animation.setStartValue(float(start or 0.0))
        animation.setEndValue(1.0 if on else 0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic if on else QEasingCurve.Type.InCubic)

        def step(value, e=effect) -> None:
            e.setBlurRadius(GLOW_RADIUS * value)
            e.setColor(QColor(255, 196, 60, int(190 * value)))

        animation.valueChanged.connect(step)
        if not on:
            animation.finished.connect(lambda e=effect: e.setEnabled(False))
        self.animations[widget] = animation
        widget.destroyed.connect(lambda *_: self.animations.pop(widget, None))
        animation.start()


class Toast(QWidget):
    """An achievement-style alert (cinematic_fx.draw_banner) that slides in from the right edge of its parent's
    area, stays a few seconds and fades out. done is called once it has gone."""

    def __init__(self, parent: QWidget, heading: str, title: str, place: str, badge: str, color: QColor,
                 icon=None, done=None, life_ms: int = TOAST_MS):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.parts = (heading, title, place, badge, color, icon)
        self.done = done
        self.opacity = 0.0
        self.offset = 1.0                   # share of the slide still to go
        self.resize(430, 92)
        self.slide = QVariantAnimation(self)
        self.slide.setDuration(SLIDE_MS)
        self.slide.setStartValue(0.0)
        self.slide.setEndValue(1.0)
        self.slide.setEasingCurve(QEasingCurve.Type.OutBack)
        self.slide.valueChanged.connect(self._entered)
        self.leave = QVariantAnimation(self)
        self.leave.setDuration(FADE_MS * 2)
        self.leave.setStartValue(1.0)
        self.leave.setEndValue(0.0)
        self.leave.valueChanged.connect(self._fading)
        self.leave.finished.connect(self._gone)
        QTimer.singleShot(life_ms, self, self.leave.start)

    def place(self, right: int, top: int) -> None:
        self.anchor = (right, top)
        self._move()

    def start(self) -> None:
        self.show()
        self.raise_()
        self.slide.start()

    def _move(self) -> None:
        right, top = getattr(self, "anchor", (self.parentWidget().width() - 16, 16))
        self.move(int(right - self.width() + 40 * self.offset), int(top))

    def _entered(self, value) -> None:
        self.offset, self.opacity = 1 - value, min(1.0, value * 2)
        self._move()
        self.update()

    def _fading(self, value) -> None:
        self.opacity = value
        self.update()

    def _gone(self) -> None:
        self.hide()
        if self.done:
            self.done(self)
        self.deleteLater()

    def paintEvent(self, event) -> None:
        from .cinematic_fx import draw_banner
        painter = QPainter(self)
        painter.setOpacity(max(0.0, self.opacity))
        draw_banner(painter, QRectF(self.rect()), *self.parts)
        painter.end()


class ToastQueue(QObject):
    """Shows toasts one below the other at the top right of an area (a widget of the window)."""

    def __init__(self, area: QWidget, config):
        super().__init__(area)
        self.area, self.config = area, config
        self.toasts: list[Toast] = []

    def show(self, heading: str, title: str, place: str = "", badge: str = "★", color=None, icon=None) -> Toast:
        window = self.area.window()
        toast = Toast(window, heading, title, place, badge, QColor(color or theme.GOLD), icon, self._gone,
                      TOAST_MS if enabled(self.config) else TOAST_MS // 2)
        self.toasts.append(toast)
        self._layout()
        if enabled(self.config):
            toast.start()
        else:
            toast.offset, toast.opacity = 0.0, 1.0
            toast._move()
            toast.show()
        return toast

    def _gone(self, toast: Toast) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
        self._layout()

    def _layout(self) -> None:
        window = self.area.window()
        corner = self.area.mapTo(window, self.area.rect().topRight())
        y = corner.y() + 14
        for toast in self.toasts:
            toast.place(corner.x() - 14, y)
            y += toast.height() + 6
