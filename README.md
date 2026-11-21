# 拾流 · Media Harbor

拾流是一款 Windows x64 下载管理器。可以粘贴 B 站、YouTube 或媒体链接，选择画质或单独保存音频，也可以通过 Chrome / Edge 扩展从当前网页选取视频、音频和图片。

**[下载 Windows x64 安装包](https://github.com/Jonathan1He/media-harbor/releases/latest/download/MediaHarbor-Setup-x64.exe)** · [版本记录与校验值](https://github.com/Jonathan1He/media-harbor/releases)

![拾流下载管理窗口与保存目录选择，使用示例队列](output/desktop-preview.png)

## 安装与使用

1. 运行安装包，安装到当前 Windows 账户。在开始菜单搜索「拾流」。桌面端可独立使用。
2. 需要网页按钮时，打开 `edge://extensions` 或 `chrome://extensions`，开启开发者模式，选择「加载已解压的扩展程序」，指定安装结束时打开的 **extension** 文件夹。刷新之前打开的网页。
3. 在播放器点「下载视频」，或在桌面按 **Ctrl+N** 添加并解析链接。在「确认下载」里选择文件夹，再点「开始下载」。拾流记住最近 8 个位置，批量保存图片只需选一次。关闭下载确认时使用设置中的默认目录。
4. 在左侧按状态或媒体类型查看任务。工具栏和右键菜单支持暂停、继续、重试或定位文件。退出时正在执行的任务会在下次启动时恢复，网站签发的临时资源可能需要返回原网页重新选择。

## 解析与下载

- **B 站**支持普通 BV/av 投稿页，链接中的 `?p=2` 表示第二分 P。画质来自当前实际返回的视频轨道。匿名下载实测样片 BV15BSdBBELf 为 852 × 480、约 30 fps、H.264 + AAC，54.45 秒，整片解码通过。
- **YouTube** 实测匿名下载 Blender 基金会《Big Buck Bunny》，成品为 1920 × 1080、60 fps，包含 AV1 视频和 AAC 音频。自动画质优先选择来源实际提供的最高 1080p 档。
- **浏览器播放器**可按次选择「用当前播放器重试」，读取当前页面提供的可保存资源。账号登录留在平台网站，拾流不接收账号密码或浏览器 Cookie。仅下载有权保存的内容。
- **通用媒体**支持直链、HLS、DASH 及图片批量保存。SQLite 队列持久化，独立下载进程负责传输和成品校验。Edge 的扩展加载及 Windows 原生通信已实测，Chrome 正式版手动加载后的完整流程、B 站登录后的 1080p 和同文件 FDM 速度对照尚未验证。

## 源码与构建

| 路径 | 用途 |
| --- | --- |
| `desktop.py`、`desktop_ui.py` | Windows 窗口、任务队列与历史保存位置 |
| `core.py`、`engine.py`、`bridge.py` | 持久化、媒体解析与下载、浏览器原生通信 |
| `extension/` | Chrome 和 Edge 的 Manifest V3 扩展 |
| `packaging/` | Windows 启动器、安装器、构建脚本与第三方组件说明 |
| `tests/` | 下载、B 站分 P、桌面通信与浏览器验收 |

构建需要 Windows x64、包含 Tcl/Tk 的 CPython 3.12，以及 Windows .NET Framework 4.x 的 C# 编译器。准备一个依赖目录，将 `yt-dlp[default]` 和 Pillow 安装到其中的 `vendor/`，将 FFmpeg、ffprobe、aria2c、Node.js 的 Windows 可执行文件及依赖放到 `tools/`，将组件许可证放到 `licenses/`。组件版本和来源见[第三方组件清单](packaging/THIRD-PARTY.md)。

在项目根目录运行 `python packaging/build.py <依赖目录>`，得到 `output/MediaHarbor-Setup-x64.exe`。安装器支持 `--extract <新目录>`，可仅解包用于核验。通过 `HARBOR_DATA`、`HARBOR_TOOLS`、`HARBOR_VENDOR` 可将测试与日常下载记录隔离。

运行 `python tests/acceptance.py <临时目录>` 验证本地传输，`python tests/bilibili_posts.py` 验证 B 站格式和分 P 处理，`python tests/desktop_native.py <解包目录> <临时目录>` 验证桌面通信和目录记忆。浏览器测试见 `tests/browser.cjs`。

