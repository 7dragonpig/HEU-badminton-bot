# HRBEU 羽毛球场自动抢场

哈尔滨工程大学体育场馆预订系统 (yuding.hrbeu.edu.cn) 的自动抢场脚本。

## 功能

- 🔐 自动 CAS 登录（支持验证码自动识别）
- ⏰ 定时抢场，精确到秒
- 🏸 多场地优先级/降级策略（如：6号 → 9号 → 任意空场）
- 🔄 同时抢多个时段，共享登录只需一次
- 🍪 Cookie 复用，避免重复登录

## 原理

- **每天 21:00** 开放抢后天的场地
- 脚本提前启动 Chrome，登录并预热页面
- 到准点时快速执行选场→下单（~2-3秒）

## 依赖

- Python 3.8+
- Selenium + Chrome 浏览器
- 验证码识别服务（二选一）：
  - [超级鹰](https://www.chaojiying.com/) — 推荐，识别速度快
  - [云码](http://www.jfbym.com/)

```bash
pip install selenium requests
```

## 配置

复制示例配置并填入你的信息：

```bash
cp config.example.json config.json
```

编辑 `config.json`：

| 字段 | 说明 |
|------|------|
| `username` | 学号 |
| `password` | 密码 |
| `captcha_provider` | 验证码平台：`chaojiying` 或 `yunma` |
| `cjy_user/cjy_pass/cjy_soft_id` | 超级鹰账号信息 |
| `yunma_token` | 云码 token |

## 使用

### 单时段抢场

```bash
# 抢 2026-05-08 的 15:00，优先6号场，备选9号
python auto_book.py --court 6 --fallback-courts 9,any --time 15:00 --date 2026-05-08

# 指定准点抢（提前预热，21:00整开抢）
python auto_book.py --court 6 --time 15:00 --date 2026-05-08 --book-at 21:00

# 复用已有 cookie（跳过登录）
python auto_book.py --court 6 --time 15:00 --date 2026-05-08 --reuse-session
```

### 双时段并行抢场

```bash
# 同时抢 15:00 和 16:00，共享一次登录
python book_both.py --book-at 21:00 --date 2026-05-08 --times 15:00,16:00
```

### 配合定时任务

```bash
# Linux crontab（20:55 启动，21:00 准点抢）
55 20 * * * cd /path/to/hrbeu-badminton && python book_both.py --book-at 21:00 --date $(date -d "+2 days" +\%Y-\%m-\%d)
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `auto_book.py` | 主脚本：登录 + 预热 + 抢场 |
| `book_both.py` | 并行抢两个时段 |
| `config.example.json` | 配置模板（复制为 config.json 使用） |

## 注意事项

- `config.json` 含个人账号信息，已在 `.gitignore` 中排除
- Cookie 有效期约 8 天，可用 `--reuse-session` 复用
- 验证码识别偶尔不准（取决于API服务是否稳定），脚本会自动重试（最多15次）

## License

MIT
