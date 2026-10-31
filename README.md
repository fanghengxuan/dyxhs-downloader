# dyxhs — 抖音 / 小红书下载器

命令行下载抖音视频、小红书视频和图文笔记。抖音零配置；小红书需要一份登录态 cookie。

## 安装

```bash
uv venv .venv
uv pip install -r requirements.txt
```

Playwright 直接使用系统已装的 Edge / Chrome，**不需要** `playwright install`。
如果两个浏览器都没有，再执行 `uv run playwright install chromium`。

## 使用

```bash
# 抖音：整段分享文本或链接都行
.venv\Scripts\python.exe -m dyxhs "7.68 复制打开抖音... https://v.douyin.com/xxxxx/"

# 小红书：必须是带 xsec_token 的完整链接
.venv\Scripts\python.exe -m dyxhs "https://www.xiaohongshu.com/explore/<id>?xsec_token=..."

# 指定目录 / 只看信息不下载
.venv\Scripts\python.exe -m dyxhs -o D:\videos --info "<链接>"
```

默认保存到 `~/Downloads/dyxhs`。

### 小红书登录态

大多数公开笔记**不需要登录**：工具会先用桌面 UA，被 302 到登录页时自动换手机 UA，
从手机分享页的 `noteData.data.noteData` 里拿视频/图文数据。

只有少数笔记连手机页也要求登录时，才需要 cookie。**推荐用 Cookie-Editor 导出**：

1. 在 Edge 安装 Cookie-Editor 扩展，打开并登录 xiaohongshu.com。
2. 点扩展 → Export → **Export as Netscape**，保存为 `cookies.txt`。
3. 运行：

   ```bash
   .venv\Scripts\python.exe -m dyxhs --cookies cookies.txt "<链接>"
   ```

`--browser` 在新版 Edge/Chrome 上可能因 App-Bound Encryption 读取失败，仅作备选。

## 工作原理

| 平台 | 路径 |
|---|---|
| 抖音 | 先试旧的 `_ROUTER_DATA` SSR 解析；失败后启动 headless Edge，加载视频页并截获 `/aweme/v1/web/aweme/detail/` 响应，取 `video.play_addr` 无水印直链 |
| 小红书 | 桌面 UA 被登录墙拦截时自动换手机 UA，解析手机分享页 `__INITIAL_STATE__` 的 `noteData.data.noteData`：`video.media.stream` 选视频，`imageList` 下载图文；仍失败才需要 cookie / yt-dlp 兜底 |

抖音那条 headless 路径是必需的：抖音详情接口要求 JS 挑战生成的 cookie，普通 `requests` 会返回 403 `Uifid Not Found`。

## 已知限制

- 抖音**图文作品**暂不支持，只下载视频。
- 小红书链接必须带有效的 `xsec_token`；token 会过期，重新从 App/网页复制。
- 少数笔记手机页也要求登录，此时才需要 cookie。
- 仅供个人备份/学习；下载内容请遵守平台条款和著作权。

## 调试

- `--info` 只解析、打印元数据，不下载。
- 报错信息会带上失败的环节（SSR / headless / yt-dlp / cookie 读取）。
- 单元测试：`.venv\Scripts\python.exe -m unittest discover -s tests -v`

## 致谢与许可

- 抖音 SSR 解析思路移植自 [Mithranda/agent-reach-douyin](https://github.com/Mithranda/agent-reach-douyin)（MIT，Copyright (c) 2025 Agent Eyes），详见 [NOTICE](NOTICE)。
- 小红书/抖音兜底依赖 [yt-dlp](https://github.com/yt-dlp/yt-dlp)；浏览器自动化使用 [Playwright](https://playwright.dev/)。
- 本项目以 MIT 许可发布，详见 [LICENSE](LICENSE)。

非官方项目，与抖音、小红书无关联。仅用于下载你有权访问的内容，请遵守平台服务条款和著作权法。
