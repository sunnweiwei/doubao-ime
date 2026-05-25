"""两行悬浮预览窗：上行原文（识别文本），下行译文（英文）。

供翻译实验 main_translate.py 用，和单行的 overlay.py 完全独立，互不影响。
样式与 overlay.py 一致（底部居中、不抢焦点的 NSPanel），只是多一行并加高。

可调环境变量：
  DOUBAO_OVERLAY_BOTTOM  距屏幕底部的像素（默认 90）
  DOUBAO_OVERLAY_FONT    字号（默认 18）
"""
import math
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
PAD_X = 22                              # 文字左右内边距
PAD_Y = round(FONT_SIZE * 0.5)         # 上下内边距
LINE_H = round(FONT_SIZE * 1.5)        # 单行文字高度
HEIGHT = LINE_H * 2 + PAD_Y * 2        # 两行
MIN_W = 160
PLACEHOLDER = "聆听中…"


class Overlay2(NSObject):
    def init(self):
        self = objc.super(Overlay2, self).init()
        if self is None:
            return None
        self._font_top = NSFont.systemFontOfSize_(FONT_SIZE)
        self._font_bot = NSFont.systemFontOfSize_(FONT_SIZE)

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
            NSColor.colorWithCalibratedWhite_alpha_(0.10, 0.92).CGColor())
        layer.setCornerRadius_(18.0)

        # 上行：原文；下行：译文。两行同色（白）
        top = self._make_label(self._font_top, NSColor.whiteColor(),
                               PAD_Y + LINE_H)
        bot = self._make_label(self._font_bot, NSColor.whiteColor(), PAD_Y)
        content.addSubview_(top)
        content.addSubview_(bot)

        self._panel = panel
        self._top = top
        self._bot = bot
        self._max_w = 900
        return self

    @objc.python_method
    def _make_label(self, font, color, y):
        label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(PAD_X, y, MIN_W - 2 * PAD_X, LINE_H))
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setTextColor_(color)
        label.setFont_(font)
        label.setAlignment_(NSTextAlignmentCenter)
        label.setStringValue_("")
        label.cell().setLineBreakMode_(NSLineBreakByTruncatingHead)
        return label

    @objc.python_method
    def _measure(self, text, font):
        return NSString.stringWithString_(text or "").sizeWithAttributes_(
            {NSFontAttributeName: font}).width

    @objc.python_method
    def _layout_for(self, top_text, bot_text):
        scr = NSScreen.mainScreen().frame()
        self._max_w = scr.size.width - 240
        wt = self._measure(top_text, self._font_top)
        wb = self._measure(bot_text, self._font_bot)
        measured = math.ceil(max(wt, wb)) + 16     # cell 左右还有几像素内边距
        w = max(MIN_W, min(self._max_w, measured + 2 * PAD_X))
        x = (scr.size.width - w) / 2.0
        self._panel.setFrame_display_(NSMakeRect(x, BOTTOM_MARGIN, w, HEIGHT), True)
        self._top.setFrame_(NSMakeRect(PAD_X, PAD_Y + LINE_H, w - 2 * PAD_X, LINE_H))
        self._bot.setFrame_(NSMakeRect(PAD_X, PAD_Y, w - 2 * PAD_X, LINE_H))

    # 下面这些方法只在主线程被调用（经 performSelectorOnMainThread）
    def setTexts_(self, arr):
        top = arr[0] if arr and arr[0] else PLACEHOLDER
        bot = arr[1] if arr and len(arr) > 1 else ""
        self._layout_for(top, bot)
        self._top.setStringValue_(top)
        self._bot.setStringValue_(bot or "")

    def showWindow(self):
        self._layout_for(PLACEHOLDER, "")
        self._top.setStringValue_(PLACEHOLDER)
        self._bot.setStringValue_("")
        self._panel.orderFrontRegardless()

    def hideWindow(self):
        self._panel.orderOut_(None)


def setup_app():
    """初始化 NSApplication（无 Dock 图标、不抢占前台）。须在主线程调用。"""
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    return app


class OverlayController2:
    """对外封装：任意线程安全地 show/hide/set_text（内部派发到主线程）。"""

    def __init__(self):
        self._ov = Overlay2.alloc().init()

    def show(self):
        self._ov.performSelectorOnMainThread_withObject_waitUntilDone_(
            "showWindow", None, False)

    def hide(self):
        self._ov.performSelectorOnMainThread_withObject_waitUntilDone_(
            "hideWindow", None, False)

    def set_text(self, top, bottom=""):
        self._ov.performSelectorOnMainThread_withObject_waitUntilDone_(
            "setTexts:", [top or "", bottom or ""], False)
