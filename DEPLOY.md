# 部署指南 · 公网演示版

站点为**纯静态**（无后端、无构建步骤），任意静态托管均可。数据文件（library.js / masters.js / stocks.js / data/*.json）由采集管线生成，随仓库更新。

## 方案 A：GitHub Pages（免费，5 分钟）

1. 新建 GitHub 仓库，把本目录全部文件推送到 `main` 分支（无需提交 `server.js`、`*.pyc`、`data/inbox/`）。
2. 仓库 Settings → Pages → Source 选 `main` / `/(root)` → Save。
3. 访问 `https://<你的用户名>.github.io/<仓库名>/`。

## 方案 B：Vercel / Cloudflare Pages（推荐，国内访问更稳）

- Vercel：`vercel deploy` 或网页导入仓库，Framework 选 Other，无需构建命令，输出目录填仓库根。
- Cloudflare Pages：导入仓库，构建命令留空，输出目录 `/`。

## 数据自动更新（GitHub Actions）

仓库包含 `.github/workflows/update-data.yml`：每交易日 UTC 00:57 / 10:17（北京时间 08:57 / 18:17）自动运行：

- `fetch_13f.py`：从 SEC EDGAR 刷新 17 家机构 13F（含季度环比变动 diff）
- `collector.py`：抓取新浪快讯、雪球热股、猫笔刀 RSS → `data/feed.json`
- 自动提交并推送到 `main`，站点数据随之更新

> GitHub 运行器的网络环境通常可访问本机抓不到的源（如猫笔刀备份站）。

如需 Actions 自动推送，给仓库配一个 `DATA_PAT` secret（有 repo 权限的 Personal Access Token）。

## 本地预览

```bash
npm run dev   # http://localhost:7100
```

## 上线前检查清单

- [ ] `data/13f.json` 为最新季度（Actions 会自动维护）
- [ ] `data/inbox/` 不提交（人工导入内容含个人信息）
- [ ] 定价页联系方式/支付链接（爱发电/面包多）替换占位内容
- [ ] 合规声明保留：诊断给问题不给买卖指令，不构成投资建议

## 付费墙最小实现（无后端）

1. 爱发电/面包多发 ¥199 年度商品，买家付款后手动/自动回复**访问码**；
2. 站点 `定价页` 留输入框，访问码写入 `localStorage` 解锁专业版功能（诊断次数限制、13F diff 明细、报告导出）；
3. 访问码即静态口令（如对日期取哈希），无需数据库。演示阶段也可直接开放全部功能收集反馈。
