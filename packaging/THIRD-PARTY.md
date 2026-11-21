# 随包组件

应用在 Windows 本机调用以下组件。运行时、Python 包和工具各自采用上游许可；Python 包的许可在 vendor 下对应的 dist-info 中。

- CPython 3.12，python-build-standalone 的 Windows x64 发行。许可在 runtime/LICENSE.txt 与 runtime/tcl 内。
- yt-dlp 及 yt-dlp-ejs，来源为 PyPI，对应源码 https://github.com/yt-dlp/yt-dlp 和 https://github.com/yt-dlp/ejs 。
- FFmpeg 9.0.2（Gyan essentials，随 imageio-ffmpeg 0.8.1 分发），ffprobe 2023-02-13（Gyan essentials，npm 包 @ffprobe-installer/win32-x64 5.1.0）。查看工具的 -version、-buildconf 和 -L 获取构建与许可。源代码 https://ffmpeg.org/download.html ，构建资料 https://www.gyan.dev/ffmpeg/builds/ 。
- aria2 1.37.0，来源 https://github.com/aria2/aria2/releases/tag/release-1.37.0 ，许可见 licenses/aria2-COPYING。
- Node.js 24.22.3，源码 https://github.com/nodejs/node/tree/v24.22.3 ，随附许可见 licenses/node-LICENSE.txt。

