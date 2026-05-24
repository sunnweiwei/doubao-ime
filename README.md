# doubao-ime

macOS 上的「按住说话」语音输入工具：按住热键（默认右 Option）说话，调用豆包大模型流式语音识别（ASR），把识别文本实时填进**当前光标所在的任意 App**（Terminal、浏览器、编辑器……）。不是真正的输入法，而是一个常驻后台的小程序。

## 效果

- 按住右 Option → 立刻开始录音，屏幕弹出**悬浮预览窗**实时显示识别文本。
- 松手 → 预览窗转一下（最终结果二遍纠错），把最终文本一次性填进当前光标处。
- 三种填字模式（环境变量 `DOUBAO_MODE`）：
  - `final`（默认，推荐）：说话时只在悬浮窗预览，松手一次性填入。不闪、不乱码、绝不动已有文本。
  - `commit`：每句确认后整句追加，从不退格。说话中分句上屏。
  - `live`（实验）：实时增量退格重打，最跟手但终端里易闪烁/乱码。
- 悬浮预览窗可用 `DOUBAO_OVERLAY=0` 关闭。

## 依赖

```bash
python3 -m pip install websockets sounddevice pyobjc-framework-Quartz
```

## 系统权限（macOS 系统设置 > 隐私与安全）

把以下权限授给**启动本脚本的那个终端 App**（Terminal / iTerm / VS Code 终端等）：

| 权限 | 用途 |
|---|---|
| 麦克风 Microphone | 录音（首次运行自动弹窗，点 Allow） |
| 输入监控 Input Monitoring | 全局热键监听 |
| 辅助功能 Accessibility | 把字打进其它 App |

改完开关后**重启终端**再运行。

## 运行

```bash
export DOUBAO_API_KEY=你的火山引擎APIKey   # 新版控制台的 X-Api-Key
export DOUBAO_MODE=live                    # 或 commit
python3 main.py
```

按住右 Option 说话，松手结束，Ctrl+C 退出。
想换热键改 `main.py` 里的 `HOTKEY_KEYCODE`（左 Option=58，右 Option=61）。

### 证书校验问题

若报 `CERTIFICATE_VERIFY_FAILED`（常见于网络环境替换了证书链、而 Python 用的
是自带证书库不认这些根证书），可让程序信任系统钥匙串里的根证书：

```bash
# 1. 导出根证书（含系统钥匙串里额外信任的证书）
security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain > ~/doubao_ca.pem
security find-certificate -a -p /Library/Keychains/System.keychain >> ~/doubao_ca.pem
# 如仍失败，再补登录钥匙串：
# security find-certificate -a -p ~/Library/Keychains/login.keychain-db >> ~/doubao_ca.pem

# 2. 指定给本工具（证书校验仍开启，安全）
export DOUBAO_CA_BUNDLE=~/doubao_ca.pem
```

应急也可 `export DOUBAO_INSECURE_SSL=1` 跳过证书校验，但会降低安全性，不建议长期使用。

## 结构

- `doubao_asr.py` — 豆包 ASR WebSocket 客户端，封装二进制协议（gzip+JSON），异步流式接口。
- `typer.py` — 把文本合成键盘事件打进光标处；`LiveTyper`（增量退格重打）/ `CommitTyper`（只追加）。
- `overlay.py` — 屏幕悬浮实时预览窗（不抢焦点的 NSPanel）。
- `main.py` — 全局热键监听 + 麦克风采集 + 串起识别、预览与填字。

实现要点：按下立刻开录音并把音频缓存，WebSocket 并行连接，连上后补发缓存音频，
所以按下到出字几乎无延迟。麦克风设备在启动时就打开好，按下时只是 start。

## 安全

不要把 API Key 写进代码或提交到仓库，只用环境变量 `DOUBAO_API_KEY`。