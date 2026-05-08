# HRBEU 羽毛球场自动抢场

哈尔滨工程大学体育场馆预订系统 (yuding.hrbeu.edu.cn) 的自动抢场脚本。

## 功能

- CAS 自动登录（支持验证码自动识别）
- 定时抢场，精确到秒
- 智能场地选择策略（优先级 + 自动降级）
- 单浏览器集中选择，一次提交多个时段
- Cookie 复用，避免重复登录

## 原理

- **每天 21:00** 开放抢后天的场地
- 脚本提前启动 Chrome，登录并预热页面
- 到准点时快速执行扫描→选场→下单（~5秒）

## 依赖

- Python 3.8+
- Selenium + Chrome 浏览器
- 验证码识别服务（二选一）：
  - [超级鹰](https://www.chaojiying.com/) — 推荐，识别速度快（~5秒）
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

### 智能抢场（推荐）

```bash
# 抢 2026-05-10 下午 15:00-17:00 的场地，21:00 准点开抢
python grab_smart.py --date 2026-05-10 --book-at 21:00

# 立即抢（测试用）
python grab_smart.py --date 2026-05-10

# 复用已有 cookie（跳过登录）
python grab_smart.py --date 2026-05-10 --reuse-session
```

#### 抢场策略

`grab_smart.py` 使用集中选择策略，一次扫描页面，按优先级选择多个时段后一次性提交：

1. **最优：** 8号+11号场的 15:00+16:00（有几个选几个）
2. **次优：** 相邻场 5+8 或 11+14 的 15:00+16:00
3. **退而求其次：** 任意场号的 15:00+16:00（优先凑完整2小时）
4. **最后手段：** 只剩一小时也先抢

### 单时段抢场（旧版）

```bash
# 抢 2026-05-08 的 15:00，优先8号场
python auto_book.py --court 8 --fallback-courts 11,any --time 15:00 --date 2026-05-08

# 指定准点抢（提前预热，21:00整开抢）
python auto_book.py --court 8 --time 15:00 --date 2026-05-08 --book-at 21:00
```

### 配合定时任务

```bash
# Linux crontab（20:55 启动，21:00 准点抢）
55 20 * * * cd /path/to/hrbeu-badminton && python grab_smart.py --date $(date -d "+2 days" +\%Y-\%m-\%d) --book-at 21:00
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `grab_smart.py` | **智能抢场（推荐）**：单浏览器，集中选择，多时段一次提交 |
| `auto_book.py` | 旧版主脚本：登录 + 预热 + 单时段抢场 |
| `book_both.py` | 旧版：并行抢两个时段（两个Chrome线程） |
| `config.example.json` | 配置模板（复制为 config.json 使用） |

## 更新日志

### 2026-05-08 — 智能抢场 v2

- **新增 `grab_smart.py`：** 单浏览器集中选择策略，替代旧版双线程方案
- 核心改进：先扫描所有可用格子，按优先级一次性选中多个时段，一次 `onShareBooking` 提交
- 4级回退策略：8+11 → 5+8/11+14 → 任意完整2小时 → 只剩1小时也抢
- 修复 GBK 终端 emoji 编码错误

### 2026-05-06 — 初始版本

- `auto_book.py` + `book_both.py` 双线程方案
- 超级鹰验证码识别（~5秒）
- 快速重试：场号切换不需重载页面

## 注意事项

- `config.json` 含个人账号信息，已在 `.gitignore` 中排除
- Cookie 有效期约 8 天，可用 `--reuse-session` 复用
- 验证码识别偶尔不准，脚本会自动重试（最多15次）

## License

MIT
