# DouyinIngest

[![skills.sh](https://skills.sh/b/ltppp/douyin-ingest)](https://skills.sh/ltppp/douyin-ingest)

一个面向 Claude Code、Codex 等 Agent 的 Douyin/抖音内容工作流：按点赞量采集 Top N 热门视频，
完成媒体下载、语音转文字、逐字稿校正、短视频文案/口播改写，并交付固定模板 Word 文档。

## 快速开始

### 完整 Agent 工作流（推荐）

无需先克隆仓库，直接从公开 GitHub 仓库安装完整能力：

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install \
  'douyin-ingest[agent] @ git+https://github.com/ltppp/douyin-ingest.git'
douyin-ingest setup --profile agent
douyin-ingest doctor --profile agent
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install `
  "douyin-ingest[agent] @ git+https://github.com/ltppp/douyin-ingest.git"
douyin-ingest setup --profile agent
douyin-ingest doctor --profile agent
```

`setup` 创建运行目录并安装 Playwright Chromium；`doctor --profile agent` 验证采集、媒体、
转写和 Word 交付所需能力。FFmpeg 是系统软件，Doctor 会给出当前平台的安装命令；首次转写时
才会按需下载所选 faster-whisper 模型。

安装两个通用 Agent Skills：

```bash
npx skills add https://github.com/ltppp/douyin-ingest \
  --skill douyin-content-ingest \
  --skill douyin-script-rewriter
```

首次运行不要加 `--headless`，浏览器会等待扫码登录：

```bash
douyin-ingest 'https://v.douyin.com/xxxx/' --json
```

### 只使用采集功能

不需要转写和 Word 时安装核心包即可：

```bash
python -m pip install \
  'douyin-ingest @ git+https://github.com/ltppp/douyin-ingest.git'
douyin-ingest setup --profile core
douyin-ingest doctor --profile core
```

### 源码开发

```bash
git clone https://github.com/ltppp/douyin-ingest.git
cd douyin-ingest
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,agent]'
.venv/bin/douyin-ingest setup --profile agent
.venv/bin/douyin-ingest doctor --profile agent
```

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
- **可选 Word 依赖**：`python-docx` 只存在于 `word` extra；固定模板 Word 生成使用
  `pip install -e '.[word]'`。
- **完整 Agent 依赖**：`agent` extra 同时包含 `transcribe` 与 `word` 能力；使用
  `pip install -e '.[agent]'`。它仍不会安装 FFmpeg、Chromium 或转写模型。

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

## Setup 与环境诊断

`setup` 是幂等的首次初始化命令。重复运行不会删除状态、输出或模型：

```bash
douyin-ingest setup --profile agent
# 等价独立入口
douyin-setup --profile agent
```

使用 `--skip-browser` 只创建 `storage/`、`output/`、`logs/` 和模型缓存目录；Linux 可显式添加
`--with-deps`，让 Playwright 在安装 Chromium 时同时请求系统浏览器依赖。Setup 不安装 FFmpeg、
不下载 Whisper 模型，也不读取登录凭据。

Doctor 只读检查环境，并按实际用途决定哪些能力是必需项：

| Profile | 必需能力 |
| --- | --- |
| `core` | Python 3.12、核心包、运行目录、Chromium |
| `media` | `core` + FFmpeg / FFprobe |
| `transcribe` | `media` + faster-whisper |
| `word` | Python、核心包、运行目录、python-docx；Chromium 仅提示 |
| `agent` | `core` + FFmpeg / FFprobe + faster-whisper + python-docx |

```bash
douyin-ingest doctor --profile agent
douyin-ingest doctor --profile agent --json
# 等价独立入口
douyin-doctor --profile agent --json
```

登录状态始终单独报告为警告而不是安装失败：公开单视频和有效缓存可能无需登录，主页首次采集则
按提示扫码。`--json` 的 stdout 是单个 JSON 对象；schema `1.1` 包含 `profile`、
`runtime_root`、汇总和逐项 `fix_command`。

源码/editable 安装默认把状态写在仓库的 `storage/`、`output/` 和 `logs/`。普通 wheel 安装改用
用户数据目录，避免写入 `site-packages`；可设置 `DOUYIN_INGEST_HOME=/path/to/data` 显式指定根目录。

## Agent Skills

仓库提供两个符合 Agent Skills 开放目录结构的 Skill：

- `douyin-content-ingest`：主页/单视频采集、Top N、媒体和原始转写。
- `douyin-script-rewriter`：AI 校正版逐字稿、原创改写和固定模板 Word 交付。

直接安装单个 Skill（与 `find-skills` 返回的命令格式一致）：

```bash
# 抖音热门视频采集、下载与语音转文字
npx skills add ltppp/douyin-ingest@douyin-content-ingest

# 抖音短视频文案、口播稿改写与 Word 交付
npx skills add ltppp/douyin-ingest@douyin-script-rewriter
```

查看全部或一次安装完整工作流：

```bash
npx skills add https://github.com/ltppp/douyin-ingest --list
npx skills add https://github.com/ltppp/douyin-ingest \
  --skill douyin-content-ingest \
  --skill douyin-script-rewriter
```

个人全局安装到 Claude Code 与 Codex：

```bash
npx skills add https://github.com/ltppp/douyin-ingest \
  -g -a claude-code -a codex \
  --skill douyin-content-ingest \
  --skill douyin-script-rewriter
```

Skills 只安装 Agent 指令、脚本和模板，不会代替上面的 Python/Chromium/FFmpeg 安装。

## 运行

用户主页、单视频、短链和包含链接的完整分享文案都可以作为输入。短链会自动解析为
`profile`（主页批量 Top N）或 `single_video`（只采集目标作品）：

```bash
.venv/bin/python -m project.main \
  '复制的抖音分享文案 https://v.douyin.com/xxxx/'
```

单视频输入始终只返回目标作品，不扫描作者主页，也不受 `--limit` 的 Top N 含义影响：

```bash
.venv/bin/douyin-ingest 'https://www.douyin.com/video/1234567890' --headless --json
```

安装后的 `douyin-ingest` 与历史入口 `douyin-crawl` 等价，原有 `douyin-crawl` 调用保持兼容。

主页采集首次运行会弹出浏览器。完成扫码登录后，程序自动检测登录 cookie 并继续；之后可使用
`--headless` 复用 `storage/storage_state.json`。单视频模式会先尝试匿名访问，公开作品无需登录；
匿名失败时，有头模式会回退扫码登录。主页有头模式下如果启动前的保存状态已失效，程序会自动
废弃旧状态并重新扫码一次；无头模式不会弹出登录窗口。

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

# 先保留 30–180 秒且点赞数不低于 10000 的作品，再按点赞数取前 50 条
.venv/bin/douyin-ingest 'https://v.douyin.com/xxxx/' \
  --headless --json --limit 50 --min-duration 30 --max-duration 180 \
  --min-digg-count 10000

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

`--min-duration` 与 `--max-duration` 的单位都是秒，边界值会保留。启用时长和点赞阈值后，
处理顺序固定为：先按内容时长过滤，再按 `--min-digg-count` 过滤，最后按点赞数降序取
`--limit` 条。缺少时长数据的作品在启用时长过滤时不会进入候选集。

进程退出码非零表示失败；JSON 模式下失败也会返回稳定结构：

```json
{"schema_version":"1.0","ok":false,"error":{"type":"ApiError","message":"..."}}
```

成功时每个 `videos[]` 元素包含：

- `aweme_id`
- `name`
- `digg_count`、`comment_count`、`share_count`、`collect_count`
- `duration_seconds`
- `page_url`
- `video_download_url`
- `audio_download_url`、`audio_title`、`audio_kind`
- `speech_audio_download_url`
- `speech_audio_source_url`、`speech_audio_requires_extraction`
- `speech_audio_file`（使用 `--speech-audio-dir` 或 `--transcribe` 时生成）
- `transcription`（可选）：`text`、`language`、`duration`、`model`、`segments`、
  `transcript_file`、`segments_file`
- `cover_url`

顶层 `collection_mode` 为 `profile` 或 `single_video`。单视频模式下 `total_works=1`、
`selection_limit=1`、`videos[]` 只包含目标作品。

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

## 法律声明与合理使用

本项目是独立的开源工具，与抖音、字节跳动及其关联方不存在隶属、授权、合作或背书关系。
项目名称和文档中出现的第三方商标仅用于说明兼容对象，其权利归相应权利人所有。

使用者必须自行确认其采集、保存、分析和传播行为具有合法依据，并遵守所在地法律、抖音平台
规则、内容授权和数据使用约定。尤其应当：

- 仅处理自己拥有、已获得明确授权或依法允许处理的账号与内容。
- 保持合理请求频率，不绕过验证码、登录限制、签名保护、付费机制或其他访问控制。
- 不利用本项目进行骚扰式采集、批量用户画像、敏感个人信息处理、数据出售或其他侵权活动。
- 尊重视频、音乐、文字、肖像和商标等权利；获得媒体地址不代表取得复制或再传播许可。
- 对 Cookie、登录状态、用户标识、调试响应和临时 CDN 地址执行最小化收集、限制访问和及时删除。

本项目按“现状”提供，不保证平台接口持续可用、采集结果完整准确或适合特定用途。README 中的
说明不构成法律意见，也不能替代使用者自己的合规判断；商业化、大规模采集或公开数据集发布前，
应取得必要授权并咨询熟悉适用司法辖区的专业人士。

## 开源许可证

本项目代码采用 [Apache License 2.0](LICENSE) 发布。该许可证仅适用于本仓库中有权许可的软件
与文档，不授予任何通过本工具访问或生成的第三方视频、音乐、文字、个人数据、商标或平台接口的
权利。第三方依赖继续适用各自的许可证。

登录状态、Cookie、调试请求文件和临时 CDN 地址不得提交到版本控制、公开 Issue 或日志分享中。

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
