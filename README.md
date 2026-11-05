# dyxhs

**一条命令，把抖音视频和小红书视频 / 图文保存到本地。**

粘贴分享链接或整段分享文本即可。抖音无需 Cookie；小红书默认走手机分享页，只有少数需要登录的笔记才要一份 `cookies.txt`。

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

## 简介

dyxhs 是一个 Python 命令行下载器，支持抖音视频与小红书的视频、图文笔记。它自动识别平台、清洗文件名并按作品保存到本地，也可以只解析元数据而不下载。

适合需要离线备份自己作品或已获授权内容的用户。

## 核心能力

- **抖音无水印视频**：优先解析页面 SSR 数据，失败时用 headless 浏览器截获详情接口，取 `play_addr` 直链。
- **小红书视频与图文**：桌面 UA 被登录墙拦截时自动切换手机 UA，从分享页状态中取视频流或图片列表。
- **多链接批量处理**：一次传入多个链接或分享文本，逐个下载并汇总失败数。
- **预检模式**：`--info` 只打印标题、作者、视频地址、图片数量等元数据。
- **可控输出**：`-o` 指定目录，默认 `~/Downloads/dyxhs`；文件名自动去除非法字符并去重。
- **可读的错误定位**：报错会标明失败环节（SSR / headless / yt-dlp / cookie 读取）。

## 工作方式

| 平台 | 解析路径 |
|---|---|
| 抖音 | `_ROUTER_DATA` SSR 解析 → headless Edge / Chrome 截获 `/aweme/v1/web/aweme/detail/` → yt-dlp 兜底 |
| 小红书 | 桌面 UA 解析 → 手机 UA 解析 `noteData.data.noteData` → cookie / yt-dlp 兜底 |

抖音的浏览器路径是必需的：详情接口要求 JS 挑战生成的 Cookie，普通 `requests` 请求会返回 403 `Uifid Not Found`。

## 安装

需要 Python 3、[uv](https://docs.astral.sh/uv/)，以及系统已安装的 Edge 或 Chrome。

```bash
uv venv .venv
source .venv/bin/activate         # Windows PowerShell: .venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
```

Playwright 默认复用系统浏览器，**不需要** `playwright install`。两个浏览器都没有时再执行：

```bash
uv run playwright install chromium
```

验证安装：

```bash
python -m dyxhs --help
```

## 快速开始

```bash
# 抖音：整段分享文本或链接都可以
python -m dyxhs "7.68 复制打开抖音... https://v.douyin.com/xxxxx/"

# 小红书：必须是带有效 xsec_token 的完整链接
python -m dyxhs "https://www.xiaohongshu.com/explore/<id>?xsec_token=..."

# 指定目录 / 只看信息不下载
python -m dyxhs -o ~/videos --info "<链接>"
```

默认保存到 `~/Downloads/dyxhs`。

### 小红书登录态

大多数公开笔记不需要登录。只有少数连手机分享页也要求登录时，才需要 Cookie。推荐用 Cookie-Editor 导出：

1. 在浏览器安装 Cookie-Editor，打开并登录 xiaohongshu.com。
2. 扩展菜单 → Export → **Export as Netscape**，保存为 `cookies.txt`。
3. 传入文件：

   ```bash
   python -m dyxhs --cookies cookies.txt "<链接>"
   ```

`--browser` 可直接读取浏览器 Cookie，但新版 Edge / Chrome 的 App-Bound Encryption 常导致读取失败，仅作备选。

## 系统要求与已知限制

- 代码为跨平台 Python 实现；需要系统存在 Edge / Chrome，或手动安装 Playwright Chromium。
- 抖音**图文作品**暂不支持，只下载视频。
- 小红书链接必须带有效的 `xsec_token`，过期后需重新复制。
- 下载内容请遵守平台条款与著作权；本项目仅供个人备份与学习。

## 调试与测试

```bash
python -m dyxhs --info "<链接>"                    # 只解析
python -m unittest discover -s tests -v            # 单元测试
```

## 致谢与许可

- 抖音 SSR 解析思路移植自 [Mithranda/agent-reach-douyin](https://github.com/Mithranda/agent-reach-douyin)（MIT，Copyright (c) 2025 Agent Eyes），详见 [NOTICE](NOTICE)。
- 下载兜底依赖 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，浏览器自动化使用 [Playwright](https://playwright.dev/)。
- 本项目以 MIT 许可发布，详见 [LICENSE](LICENSE)。

非官方项目，与抖音、小红书无关联。
