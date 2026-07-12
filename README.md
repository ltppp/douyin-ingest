# DouyinIngest

一个面向下游 Agent 的抖音内容采集与预处理管道，负责作品采集、热度排序、媒体提取，
并为可选的语音转写提供标准化输入。

## 架构

1. Playwright 打开抖音，首次运行等待扫码登录并保存 `storage_state`。
2. 打开目标用户主页，监听 JSON Network Response。
3. 根据作品数组、统计字段、`has_more` 和游标结构自动识别接口，不写死 URL。
4. 记录请求 URL、查询参数、Headers、Cookies 与 User-Agent，然后关闭浏览器。
5. `httpx` 复用会话并自动分页，Pydantic 解析作品，按 `digg_count` 排序。
6. CLI 可输出人类可读文本或 Agent 可解析的纯 JSON，并只保存所需的 Top N。

代码不解析 HTML，不依赖 CSS Selector，不使用 Selenium 或 BeautifulSoup。

## 安装与依赖分层

`pyproject.toml` 是 Python 依赖的唯一来源；项目不维护重复的 `requirements.txt`。需要
Python 3.12 或更高版本。

- **核心 Python 依赖**：`anyio`、`httpx`、`loguru`、`playwright`、`pydantic`。执行
  `pip install -e .` 安装，足够运行采集和 JSON 输出。
- **Playwright Chromium**：浏览器二进制不包含在 Python wheel 中，安装核心依赖后仍需单独执行
  `python -m playwright install chromium`。Linux 缺少浏览器系统库时，显式执行
  `python -m playwright install --with-deps chromium`。
- **FFmpeg / FFprobe**：不是 Python 包。使用 `--speech-audio-dir`，或 `--transcribe` 需要生成
  缺失音频时用于下载验证/音轨提取；已有非空 `speech_audio_file` 可直接复用。程序不会静默安装
  系统依赖。
- **开发依赖**：`pytest`、`pytest-asyncio`、`ruff`、`mypy`，通过 `pip install -e '.[dev]'`
  安装。
- **可选转写依赖**：`faster-whisper`（及其 CTranslate2 依赖）只存在于 `transcribe` extra；
  `pip install -e .` 不会安装它、下载模型或改变核心采集环境。需要转写时显式执行
  `pip install -e '.[transcribe]'`。

macOS / Linux 开发环境：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m playwright install chromium
```

FFmpeg 与 FFprobe 由同一个 FFmpeg 软件包提供：

| 平台 | 显式安装命令 |
| --- | --- |
| macOS（Homebrew） | `brew install ffmpeg` |
| Ubuntu / Debian | `sudo apt-get update && sudo apt-get install -y ffmpeg` |
| Windows（winget） | `winget install --id Gyan.FFmpeg -e` |

## 环境诊断

安装项目后运行独立诊断命令；它不会修改环境：

```bash
.venv/bin/douyin-doctor
.venv/bin/douyin-doctor --json
```

Windows 使用 `.venv\Scripts\douyin-doctor.exe`。Doctor 检查 Python 版本、每个核心包、
Playwright Chromium、`ffmpeg`、`ffprobe`、`storage/storage_state.json` 中的有效登录 cookie，
以及可选转写所需的 `faster-whisper`。Python、核心包和 Chromium 是必需项；媒体工具、已保存
登录状态和转写包是按功能启用的可选项。只有必需项失败时命令才返回非零退出码。

`--json` 的 stdout 是稳定、紧凑的单个 JSON 对象。每个 `checks[]` 项都包含 `id`、`status`
（`pass` / `warn` / `fail`）、`version`、`required`、`message` 和可直接执行的
`fix_command`；无需修复时命令为 `null`：

```json
{"schema_version":"1.0","ok":true,"platform":"macos","python_executable":"...","summary":{"pass":9,"warn":2,"fail":0},"checks":[{"id":"ffmpeg","label":"ffmpeg","status":"pass","required":false,"version":"ffmpeg version 8.1 ...","message":"Executable found: /opt/homebrew/bin/ffmpeg","fix_command":null}]}
```

源码/editable 安装默认把状态写在仓库的 `storage/`、`output/` 和 `logs/`。普通 wheel 安装改用
用户数据目录，避免写入 `site-packages`；可设置 `DOUYIN_INGEST_HOME=/path/to/data` 显式指定根目录。

## Codex Skill

仓库包含可分发 Skill：`skills/douyin-content-ingest/`。从仓库根目录复制安装到 Codex：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/douyin-content-ingest "${CODEX_HOME:-$HOME/.codex}/skills/"
```

开发时可使用符号链接，让仓库修改立即生效：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -sfn "$(pwd)/skills/douyin-content-ingest" \
  "${CODEX_HOME:-$HOME/.codex}/skills/douyin-content-ingest"
```

Windows PowerShell 可创建目录联接：

```powershell
$homeDir = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { "$HOME/.codex" }
New-Item -ItemType Directory -Force "$homeDir/skills" | Out-Null
New-Item -ItemType Junction -Force `
  "$homeDir/skills/douyin-content-ingest" `
  (Resolve-Path "skills/douyin-content-ingest")
```

安装后可用 `$douyin-content-ingest` 显式调用；其触发范围包括抖音主页 Top N、口播音频、
原始转写稿和内容分析素材准备。

## 运行

用户主页、短链和包含短链的完整分享文案都可以作为输入：

```bash
.venv/bin/python -m project.main \
  '复制的抖音分享文案 https://v.douyin.com/xxxx/'
```

安装后的 `douyin-ingest` 与历史入口 `douyin-crawl` 等价，原有 `douyin-crawl` 调用保持兼容。

首次运行会弹出浏览器。完成扫码登录后，程序自动检测登录 cookie 并继续；之后可使用
`--headless` 复用 `storage/storage_state.json`。有头模式下如果启动前的保存状态已失效，程序会
自动废弃旧状态并重新扫码一次；无头模式不会弹出登录窗口。

常用参数：

```bash
# 重新扫码登录
.venv/bin/python -m project.main 'https://www.douyin.com/user/xxx' --force-login

# 保存接口调试样本
.venv/bin/python -m project.main 'https://www.douyin.com/user/xxx' --debug

# 使用已有登录状态，无头发现接口
.venv/bin/python -m project.main 'https://www.douyin.com/user/xxx' --headless
```

## 可选 faster-whisper 转写

独立转写本地音频：

```bash
.venv/bin/douyin-transcribe audio.mp3 --json --model base
```

默认配置为 `base` 模型、中文 `zh`、启用 VAD、`device=cpu` 和 `compute_type=int8`，束搜索
`beam_size=5`。可使用 `--device`、`--compute-type`、`--language`、`--beam-size`、`--no-vad`
和 `--output-dir` 覆盖；`--language auto` 启用语言检测。

对采集得到的 Top N 自动准备音频并批量转写：

```bash
.venv/bin/douyin-crawl 'https://www.douyin.com/user/xxx' \
  --headless --json --limit 10 --transcribe
```

该模式优先复用每条视频已有且有效的 `speech_audio_file`，缺失时使用现有媒体流程下载原声或
通过 FFmpeg 从视频提取音轨。一次命令只加载一个 `WhisperModel`，并复用于全部 Top N 音频。
可用 `--speech-audio-dir` 和 `--transcript-dir` 自定义输出目录；独立命令与采集命令共享模型、
设备、计算类型、语言、束搜索、VAD、缓存和离线参数。

模型默认缓存在运行数据根目录的 `models/faster-whisper/`。首次使用某个模型时日志会明确提示
可能从 Hugging Face 下载；模型大小不属于项目安装包。用 `--model-cache-dir PATH` 更改缓存，
或用 `--offline` 禁止联网。离线缓存缺失/损坏时命令会返回明确的模型加载错误，不会自动回退
联网。未安装可选依赖时，JSON 错误包含可执行修复命令：

```json
{"schema_version":"1.0","ok":false,"error":{"type":"TranscriptionDependencyError","message":"...","fix_command":"pip install -e '.[transcribe]'"}}
```

每次转写保存 `<id>.txt` 纯文本和 `<id>.segments.json` 时间戳片段。这里只保存 faster-whisper
原始机器结果，不进行 LLM 润色、纠错、摘要或内容仿写。

## Agent / 工具调用

使用 `--json` 时，stdout 只包含 JSON，运行日志全部写入 stderr。默认返回并保存点赞最高的
10 条；`--limit XX` 同时控制内存中保留的作品数和 `output/result.json` 的 `videos` 数量。

```bash
# Agent 常用：返回 Top10
.venv/bin/douyin-ingest 'https://v.douyin.com/xxxx/' --headless --json

# 只返回点赞数不低于 10000 的前 50 条
.venv/bin/douyin-ingest 'https://v.douyin.com/xxxx/' \
  --headless --json --limit 50 --min-digg-count 10000

# 忽略 30 分钟结果缓存，强制刷新点赞数
.venv/bin/douyin-ingest 'https://v.douyin.com/xxxx/' --headless --json --refresh

# 为 Top10 下载或提取可直接交给语音分析的 MP3 文件
.venv/bin/douyin-ingest 'https://v.douyin.com/xxxx/' \
  --headless --json --speech-audio-dir output/speech_audio

# 为 Top10 准备音频并保存原始转写
.venv/bin/douyin-crawl 'https://v.douyin.com/xxxx/' \
  --headless --json --limit 10 --transcribe
```

首次精确计算 Top N 仍需遍历全部作品元数据，因为抖音用户作品接口按发布时间而不是点赞数排序。
正数 `--limit` 不会下载或保留全部视频，只维护一个固定大小的 Top-N 堆；仅显式设置
`--limit 0` 时才保留全部作品元数据。分页间默认随机等待 0.4–0.9 秒，结果默认缓存 1800 秒；
缓存命中时不会启动浏览器或请求作品分页。可用 `--cache-ttl 0` 禁用缓存，或用
`--page-delay-min/--page-delay-max` 调整节流范围。

进程退出码非零表示失败；JSON 模式下失败也会返回稳定结构：

```json
{"schema_version":"1.0","ok":false,"error":{"type":"ApiError","message":"..."}}
```

成功时每个 `videos[]` 元素包含：

- `aweme_id`
- `name`
- `digg_count`、`comment_count`、`share_count`、`collect_count`
- `page_url`
- `video_download_url`
- `audio_download_url`、`audio_title`、`audio_kind`
- `speech_audio_download_url`
- `speech_audio_source_url`、`speech_audio_requires_extraction`
- `speech_audio_file`（使用 `--speech-audio-dir` 或 `--transcribe` 时生成）
- `transcription`（可选）：`text`、`language`、`duration`、`model`、`segments`、
  `transcript_file`、`segments_file`
- `cover_url`

Python Agent 调用示例：

```python
import json
import subprocess

process = subprocess.run(
    [
        ".venv/bin/douyin-ingest",
        "https://v.douyin.com/xxxx/",
        "--headless",
        "--json",
        "--limit",
        "10",
    ],
    capture_output=True,
    text=True,
    check=False,
)
payload = json.loads(process.stdout)
if process.returncode != 0 or not payload["ok"]:
    raise RuntimeError(payload["error"]["message"])
videos = payload["videos"]
```

`video_download_url` 是作品响应中的直接播放/下载 CDN 地址；`audio_download_url` 来自
`music.play_url`。仅当 `audio_kind=original_sound` 且该地址不依赖 Cookie 时，它也会出现在
`speech_audio_download_url`。背景音乐或需 Cookie 的原声不会被误标为可直接使用的口播，此时
`speech_audio_requires_extraction=true`，应从 `speech_audio_source_url` 下载视频并用 FFmpeg
提取完整音轨。使用 `--speech-audio-dir` 可自动完成这一步：原声直接下载，背景音乐作品从
Top N 视频提取 MP3，并在 `speech_audio_file` 返回本地绝对路径。该选项始终需要 `ffprobe`
验证产物；从视频提取音轨时还需要 FFmpeg。媒体地址可能过期，应尽快使用并携带顶层
`download_headers`。

`--debug` 会写入：

- `output/debug/request_headers.json`
- `output/debug/request_cookie.json`
- `output/debug/request_query.json`
- `output/debug/response_sample.json`

这些文件包含敏感登录信息，默认不生成、已加入 `.gitignore`，并强制使用 `0600` 权限。

## 输出

`output/result.json` 包含：

- `user.nickname`
- `user.sec_user_id`
- `total_works`
- `top1`
- `top10`
- `videos`（所需 Top N，按点赞数降序）
- `selection_limit`、`cache_hit`
- `download_headers`

日志写入 `logs/crawler.log`，登录状态写入 `storage/storage_state.json`（权限 `0600`）。
如果用户详情接口提供 `aweme_count`，程序会在分页结束时核对去重后的作品数；后续页异常返回
空列表也会按不完整结果报错，不会静默写入成功文件。

## 已知边界与替代方案

抖音可能让 `a_bogus` 等签名与完整查询串绑定。捕获首请求后直接替换游标，可能令第二页
签名失效；程序会识别这种情况并抛出明确错误，不会把不完整结果当成成功。

长期稳定性从高到低的选择是：

1. 有授权条件时使用抖音开放平台或数据导出，维护成本最低，但字段和权限受平台限制。
2. 当前架构加一个独立、可测试的合规签名服务；HTTP 分页性能好，但签名变化带来维护成本。
3. 让浏览器继续滚动翻页最容易适配签名变化，但违反本项目“Playwright 后续不参与采集”的边界，
   资源占用和可观测性也更差。

本 MVP 选择诚实暴露第 2 项缺口，而不是内置易失效的逆向签名实现。

## 合规与安全

仅在获得授权并符合适用法律、抖音平台规则和数据使用约定的场景中使用本项目。保持合理请求
频率，不尝试绕过验证码、访问控制或签名保护。登录状态、Cookie、调试请求文件和临时 CDN
地址不得提交到版本控制、公开 Issue 或日志分享中。

## 验证

```bash
.venv/bin/pytest -q
.venv/bin/ruff check project tests
.venv/bin/mypy project
```

标准测试通过假后端验证转写，不下载模型。需要用本机真实 MP3 和已安装的可选依赖运行 smoke test：

```bash
DOUYIN_TRANSCRIBE_SMOKE_MP3=/absolute/path/to/audio.mp3 \
  .venv/bin/pytest -q -m smoke tests/test_transcription.py
```

可设置 `DOUYIN_TRANSCRIBE_SMOKE_MODEL=base`；已有完整缓存时再设置
`DOUYIN_TRANSCRIBE_SMOKE_OFFLINE=1` 验证离线加载。
