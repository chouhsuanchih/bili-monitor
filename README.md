# B站 UP 主更新监控（Server酱 + GitHub Actions）

零成本、无需服务器：由 GitHub Actions 每 30 分钟定时检查你关注的 UP 主，
发现新投稿 / 新动态时，通过 **Server酱** 推送到你的**微信**。

---

## 一、它做什么

1. 定时拉取指定 UP 主的「空间动态」；
2. 与上次记录比对，发现新内容；
3. 把「UP 名 + 时间 + 标题 + 链接」推到微信。
4. 首次运行只记录基线、不推送（避免一上来就刷屏）；之后只推新内容。

监控的内容类型默认包括：**视频投稿、图文动态、纯文字动态、专栏**（不含转发）。

---

## 二、准备三样东西

### 1. GitHub 账号
没有的话去 <https://github.com> 免费注册一个。

### 2. Server酱 SendKey（微信推送）
1. 打开 <https://sct.ftqq.com>；
2. 用**微信扫码登录**；
3. 页面上即为 `SendKey`（形如 `SCTxxxxxxxx...`），复制保存。

> 免费版每天 5 条消息、每分钟最多 50 条，对本场景足够（脚本会把一次检查到的多条更新合并成 1 条推送）。
> 想要更多额度可付费（约 3 元/月），非必需。

### 3. 要监控的 UP 主 UID
- 电脑浏览器打开 UP 主主页，地址栏形如 `https://space.bilibili.com/946974`，
  其中的数字 `946974` 就是 UID；
- 或手机 App 进入主页 → 右上角分享 → 复制链接，链接里的数字即 UID。

拿到后填入 `config.json` 的 `ups` 数组，可以填多个：

```json
{
  "ups": [
    { "mid": "946974", "name": "影视飓风" },
    { "mid": "546195",  "name": "老番茄" }
  ]
}
```

---

## 三、部署到 GitHub（推荐：关机也能监控）

1. **新建仓库**：GitHub 右上角 `+` → New repository，名字随意（如 `bili-monitor`），
   可设为 Private（私有仓库 Actions 每月免费 2000 分钟，足够）。
2. **上传文件**：把本文件夹里的全部内容按原样传上去，务必保持目录结构，
   特别注意 `.github/workflows/monitor.yml` 这个路径不能变。
   （网页端可直接拖拽上传；会写命令行的用 `git` 更省事。）
3. **配置 SendKey**：仓库 → `Settings` → `Secrets and variables` → `Actions`
   → `New repository secret`：
   - Name 填 `SERVERCHAN_SENDKEY`，Secret 填你第 2 步拿到的 SendKey
   - （可选）再加一条 `BILI_COOKIE`，填入你的 B站 Cookie，能提高抓取成功率（见第五节）
4. **开放写入权限**（用于保存状态）：仓库 → `Settings` → `Actions` → `General`
   → 拉到最下面 `Workflow permissions` → 选 **Read and write permissions** → 保存。
5. **测试**：仓库 → `Actions` → 左边选 `Bilibili Monitor` → 右侧 `Run workflow`。
   第一次运行只记录基线、不推送，属正常现象；等 UP 主下次更新就会收到微信。

---

## 四、在本机运行（不想用 GitHub 时的备选）

前提：电脑装了 Python 3，且能联网。

```bash
cd bili-monitor
pip3 install -r requirements.txt
export SERVERCHAN_SENDKEY="你的SendKey"   # Windows 用 set，PowerShell 用 $env:
export BILI_COOKIE="你的B站Cookie"       # 可选，配置后抓取成功率更高
python3 monitor.py
```

想让它自动定时跑：
- **macOS**：用 `launchd` 或 `crontab -e` 加一行（例如每 30 分钟）：
  `*/30 * * * * cd /路径/bili-monitor && SERVERCHAN_SENDKEY=xxx /usr/bin/python3 monitor.py`
- **Windows**：用「任务计划程序」定时执行 `python monitor.py`。

> 缺点：电脑关机 / 休眠时不检查。这也是推荐用 GitHub Actions 的原因。

---

## 五、重要说明（请务必看）

### 关于 B站风控（关键）
B站对「拉取 UP 主动态」这个接口风控较严，可能出现几种表现：`-352` 错误、
「返回成功但数据为空」的软风控，网络环境不佳时（例如服务器位于海外）还可能直接返回 `412`。
实测在无任何处理时，单次请求成功率约 15%。

脚本已内置应对：
- 自动获取 `buvid3/buvid4` 凭证；
- **单轮最多重试 12 次**，失败会自动换会话、换凭证，直到成功或本轮放弃；
- 「返回空数据」也会被当作疑似风控重试，**不会误判为「没有更新」**。

两种结果的差别：
- 某轮 12 次都失败时：脚本跳过该 UP，**等下一周期重试，不会漏消息**，只是通知可能晚 30~60 分钟；
- 配置你自己的 B站 Cookie（见下）**能明显提高成功率**，网络环境不佳时尤其有效。

### 如何配置 B站 Cookie（可选，配置后成功率更高）
1. 电脑浏览器登录 B站，按 F12 打开开发者工具 → `Network` → 刷新页面 → 随便点一个 `api.bilibili.com` 的请求
   → `Request Headers` 里找到 `Cookie`，整段复制（重点是 `SESSDATA=...` 那一段）。
2. **GitHub Actions 用户**：仓库 `Settings` → `Secrets and variables` → `Actions` → `New repository secret`，
   Name 填 `BILI_COOKIE`，值粘贴那串 Cookie。
   **本机运行用户**：设置环境变量 `BILI_COOKIE` 即可。

> ⚠️ 安全提醒：Cookie 等同于你的账号登录凭证，只能填在**加密的 Secret / 本地环境变量**里，
> 不要写进 `config.json`，也不要直接提交到仓库。它通常 1~2 个月过期，到期后重新获取一次即可。

### 其他
- **定时可能有延迟**：GitHub 的定时任务在高峰期可能延后几分钟到十几分钟，不承诺精确到分钟。
- **仓库闲置会停**：GitHub 会在仓库连续 60 天无活动后自动暂停定时任务。偶尔手动点一次
  `Run workflow`，或给仓库随便提交点东西即可保持。
- **隐私**：`SendKey` 与 `BILI_COOKIE` 只存在 GitHub 的加密 Secret 里，脚本不会外传，也不会写进任何文件；仓库建议设为 Private。

---

## 六、常见问题

**Q：一直收不到微信？**
1. 先在 Server酱 网页点「发送测试消息」，确认微信通道正常；
2. 确认仓库 Secret 名严格是 `SERVERCHAN_SENDKEY`；
3. 确认 Actions 里那次运行是绿色通过（失败会显示红叉，点进去看日志）。

**Q：日志里一直出现 412 / 抓不到数据？**
多半是 B站 Cookie 过期了（有效期约 1~2 个月）。重新复制一次 Cookie 并更新 `BILI_COOKIE` Secret 即可。

**Q：推送太频繁 / 只想看视频不想看图文？**
改 `config.json` 的 `allow_types`，只保留 `DYNAMIC_TYPE_AV` 即可只看视频投稿。

**Q：想改检查频率？**
改 `.github/workflows/monitor.yml` 里的 `cron`。注意 GitHub 的 cron 用 **UTC 时间**，
最短间隔 5 分钟（不建议设太短，容易加重风控）。
