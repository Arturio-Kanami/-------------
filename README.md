# 小鹅通本地下载与转写工作台

制作人林祭Linki。  
关注《贝城奠基者》谢谢喵。
https://space.bilibili.com/3546713514052350?spm_id_from=333.337.0.0

秉持互联网开源精神，该程序禁止用于商业途径，但是欢迎免费分享传播。

## 这是什么

这是一个本地 Web UI 工具，用于归档你自己账号已经购买且能正常播放的小鹅通课程内容。

它不会绕过登录、付费、DRM 或平台访问限制。工作流程是：

1. 打开真实的 Edge 浏览器窗口。
2. 你正常登录自己的已购课程账号。
3. 进入课节并开始播放。
4. 程序记录浏览器已经有权限请求的媒体地址。
5. 你可以下载视频，或仅下载音频。
6. 可用本地 faster-whisper 转写成纯文本 `.txt`。

## 功能

- Edge 登录态捕获。
- 捕获 `m3u8` / `mp4` 媒体地址。
- 下载视频。
- 仅下载音频为 `.m4a`。
- 本地 faster-whisper 转写。
- 只输出纯文本 `.txt`，不生成时间轴、字幕或 JSON。
- 自动检测 ffmpeg、GPU/CUDA 运行状态。

## 使用前提

- Windows 10/11。
- 已安装 Microsoft Edge。
- 已安装 Python 3.10 或更高版本。
- 使用者只能下载自己拥有合法访问权限的内容。

## 安装依赖

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-transcribe.txt
```

如果你使用 release 压缩包，直接双击 `open_xiaoe_workbench.bat`，首次运行会尝试自动安装依赖。

## 启动 Web UI

双击：

```text
open_xiaoe_workbench.bat
```

或：

```text
start_web_ui.bat
```

然后打开：

```text
http://127.0.0.1:8765/
```

## 下载流程

1. 点击 Web UI 中的“启动捕获”。
2. 在打开的 Edge 窗口中正常登录。
3. 进入你已经购买的课节并播放。
4. 回到 Web UI，在“已捕获媒体”中选择：
   - `下载视频`
   - `仅音频`

下载结果默认保存到：

```text
downloads/
```

## 转写流程

在 Web UI 中点击下载文件旁边的“转写”，或在“本地转写”区域选择文件/文件夹。

文字稿默认保存到：

```text
transcripts/
```

每个音视频文件只生成一个纯文本：

```text
*.txt
```

## 模型

默认推荐 `medium`。如果第一次使用某个模型，本工具会尝试下载模型到：

```text
models/
```

如果网络访问 Hugging Face 不稳定，脚本会优先使用 `https://hf-mirror.com`。

## GPU

如果安装了 NVIDIA 显卡和 CUDA/cuDNN 运行库，程序会优先使用 GPU。

`requirements-transcribe.txt` 中包含可通过 pip 安装的 CUDA 12/cuDNN 运行库包：

- `nvidia-cublas-cu12`
- `nvidia-cudnn-cu12`
- `nvidia-cuda-nvrtc-cu12`

如果 GPU 不可用，程序会自动回退到 CPU。

## 发布/分享注意

不要提交或分享以下目录：

```text
.xiaoe_browser_profile/
downloads/
transcripts/
models/
release/
```

它们可能包含登录资料、课程文件、文字稿、大模型或构建产物。

## 许可

见 [LICENSE.txt](LICENSE.txt)。

简要说明：

- 允许免费使用、复制、分享和传播。
- 禁止商业用途。
- 不得用于绕过登录、付费、DRM、加密保护或平台访问限制。
