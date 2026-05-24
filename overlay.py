"""屏幕悬浮预览窗：说话时实时显示识别文本，不触碰目标输入框。

用一个不抢焦点的半透明 NSPanel 实现（NonactivatingPanel），所以合成的
键盘事件仍然送往你原来聚焦的 App。所有 UI 操作都派发到主线程执行。
"""
import objc
from Foundation import NSObject, NSMakeRect
from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSPanel, NSColor,
    NSTextField, NSFont, NSScreen, NSBackingStoreBuffered,
    NSStatusWindowLevel, NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel, NSLineBreakByTruncatingHead,
)

W, H = 820, 96


class Overlay(NSObject):
    def init(self):
        self = objc.super(Overlay, self).init()
        if self is None:
            return None
        scr = NSScreen.mainScreen().frame()
        x = (scr.size.width - W) / 2.0
        y = scr.size.height * 0.16
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, W, H), style, NSBackingStoreBuffered, False)
        panel.setLevel_(NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.82))
        panel.setHasShadow_(True)
        panel.setReleasedWhenClosed_(False)
        panel.setHidesOnDeactivate_(False)
        panel.setIgnoresMouseEvents_(True)
        content = panel.contentView()
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(20.0)

        label = NSTextField.alloc().initWithFrame_(NSMakeRect(28, 0, W - 56, H))
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(NSFont.systemFontOfSize_(32))
        label.setStringValue_("")
        label.cell().setLineBreakMode_(NSLineBreakByTruncatingHead)
        content.addSubview_(label)

        self._panel = panel
        self._label = label
        return self

    # 下面这些方法只在主线程被调用（经 performSelectorOnMainThread）
    def setText_(self, s):
        self._label.setStringValue_(s or "")

    def showWindow(self):
        self._panel.orderFrontRegardless()

    def hideWindow(self):
        self._panel.orderOut_(None)


def setup_app():
    """初始化 NSApplication（无 Dock 图标、不抢占前台）。须在主线程调用。"""
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    return app


class OverlayController:
    """对外封装：任意线程安全地 show/hide/set_text（内部派发到主线程）。"""

    def __init__(self):
        self._ov = Overlay.alloc().init()

    def show(self):
        self._ov.performSelectorOnMainThread_withObject_waitUntilDone_(
            "showWindow", None, False)

    def hide(self):
        self._ov.performSelectorOnMainThread_withObject_waitUntilDone_(
            "hideWindow", None, False)

    def set_text(self, text):
        self._ov.performSelectorOnMainThread_withObject_waitUntilDone_(
            "setText:", text, False)
