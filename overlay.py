"""屏幕悬浮预览窗：说话时实时显示识别文本，不触碰目标输入框。

干净的圆角"胶囊"样式，底部居中，宽度随文字自动伸缩。不抢焦点
（NonactivatingPanel），所以合成的键盘事件仍送往你原来聚焦的 App。
所有 UI 操作都派发到主线程执行。

可调环境变量：
  DOUBAO_OVERLAY_BOTTOM  距屏幕底部的像素（默认 90；想贴 Dock 设小一点，如 12）
  DOUBAO_OVERLAY_FONT    字号（默认 18）
"""
import os

import objc
from Foundation import NSObject, NSMakeRect, NSString
from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSPanel, NSColor,
    NSTextField, NSFont, NSScreen, NSBackingStoreBuffered, NSFontAttributeName,
    NSStatusWindowLevel, NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel, NSLineBreakByTruncatingHead,
    NSTextAlignmentCenter,
)

BOTTOM_MARGIN = int(os.environ.get("DOUBAO_OVERLAY_BOTTOM", "90"))
FONT_SIZE = int(os.environ.get("DOUBAO_OVERLAY_FONT", "18"))
PAD_X = 22          # 文字左右内边距
HEIGHT = round(FONT_SIZE * 2.4)
LABEL_H = round(FONT_SIZE * 1.5)        # 单行文字高度，用于垂直居中
LABEL_Y = round((HEIGHT - LABEL_H) / 2.0)
MIN_W = 120
PLACEHOLDER = "聆听中…"


class Overlay(NSObject):
    def init(self):
        self = objc.super(Overlay, self).init()
        if self is None:
            return None
        self._font = NSFont.systemFontOfSize_(FONT_SIZE)

        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, MIN_W, HEIGHT), style, NSBackingStoreBuffered, False)
        panel.setLevel_(NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setReleasedWhenClosed_(False)
        panel.setHidesOnDeactivate_(False)
        panel.setIgnoresMouseEvents_(True)

        content = panel.contentView()
        content.setWantsLayer_(True)
        layer = content.layer()
        layer.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.10, 0.90).CGColor())
        layer.setCornerRadius_(HEIGHT / 2.0)     # 胶囊圆角

        label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(PAD_X, LABEL_Y, MIN_W - 2 * PAD_X, LABEL_H))
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(self._font)
        label.setAlignment_(NSTextAlignmentCenter)
        label.setStringValue_("")
        label.cell().setLineBreakMode_(NSLineBreakByTruncatingHead)
        content.addSubview_(label)

        self._panel = panel
        self._label = label
        self._max_w = 900
        return self

    def _layout_for(self, text):
        scr = NSScreen.mainScreen().frame()
        self._max_w = scr.size.width - 240
        measured = NSString.stringWithString_(text or "").sizeWithAttributes_(
            {NSFontAttributeName: self._font}).width
        w = max(MIN_W, min(self._max_w, measured + 2 * PAD_X + 6))
        x = (scr.size.width - w) / 2.0
        y = BOTTOM_MARGIN
        self._panel.setFrame_display_(NSMakeRect(x, y, w, HEIGHT), True)
        self._label.setFrame_(NSMakeRect(PAD_X, LABEL_Y, w - 2 * PAD_X, LABEL_H))

    # 下面这些方法只在主线程被调用（经 performSelectorOnMainThread）
    def setText_(self, s):
        text = s if s else PLACEHOLDER
        self._layout_for(text)
        self._label.setStringValue_(text)

    def showWindow(self):
        self._layout_for(PLACEHOLDER)
        self._label.setStringValue_(PLACEHOLDER)
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
