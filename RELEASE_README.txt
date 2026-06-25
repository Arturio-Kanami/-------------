小鹅通本地下载与转写工作台

制作人林祭Linki。
关注《贝城奠基者》谢谢喵。
秉持互联网开源精神，该程序禁止用于商业途径，但是欢迎免费分享传播。

使用前提
1. Windows 10/11。
2. 已安装 Microsoft Edge。
3. 已安装 Python 3.10 或更高版本，并且 python 命令可在命令行中使用。
4. 只用于下载你自己账号已经购买且能正常播放的课程内容。

启动方式
双击 open_xiaoe_workbench.bat。

第一次启动时，脚本会自动安装 Python 依赖。转写模型不会打包在 release 中，第一次转写对应模型时会自动下载。

默认地址
http://127.0.0.1:8765/

文件位置
downloads：下载的视频或音频。
transcripts：转写出的 txt 文字稿。
models：自动下载的 faster-whisper 模型。

说明
如果课程页面使用 DRM 加密，本工具不会绕过 DRM。
如果 GPU 不可用，程序会自动退回 CPU，只是速度会慢一些。
