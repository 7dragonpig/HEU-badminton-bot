#!/usr/bin/env python3
"""
HRBEU 羽毛球场智能抢场 - 单浏览器，集中选择，一次提交

策略:
  1. 优先: 8号+11号场的15:00和16:00（4个时段），有几个选几个
  2. 回退: 如果8/11全没了，抢任意场号的15:00+16:00（保证2小时完整）
  3. 都没有就拉倒

流程: scan → chose(多个) → onShareBooking → confirm → PayField

用法:
  python grab_smart.py --book-at 21:00 --date 2026-05-08
  python grab_smart.py --date 2026-05-08  # 立即抢
"""
import json, time, datetime, re, sys, os, base64, argparse, logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.json')
COOKIE_PATH = os.path.join(SCRIPT_DIR, 'session.json')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', handlers=[
    logging.StreamHandler(sys.stdout)
])
log = logging.getLogger("smart")

BASE = 'https://yuding.hrbeu.edu.cn'
BOOKING_URL = f'{BASE}/Views/Field/FieldOrder.html?VenueNo=002&FieldTypeNo=YMQ001'

# 场号标准化（页面显示为 '08'/'11' 等）
GROUP_BEST = ['08', '11']          # 最优
GROUP_ADJACENT_A = ['05', '08']     # 相邻组A: 5+8
GROUP_ADJACENT_B = ['11', '14']     # 相邻组B: 11+14
ALL_GROUPS = [GROUP_BEST, GROUP_ADJACENT_A, GROUP_ADJACENT_B]
# 目标时间段
TARGET_SLOTS = ['15:00', '16:00']


def load_config():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return json.load(f)


# ─── 登录 ───

def login(driver, cfg):
    driver.get(f"{BASE}/User/UserChoose?LoginType=1")
    time.sleep(1)
    if 'cas' not in driver.current_url:
        driver.get(f"{BASE}/User/Login")
        time.sleep(1)

    wait = WebDriverWait(driver, 30)
    uname = None
    for sel in ['input[name="username"]', '#username', 'input[type="text"]']:
        try:
            els = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, sel)))
            for el in els:
                if el.is_displayed():
                    uname = el
                    break
            if uname:
                break
        except:
            continue

    pwd = None
    for sel in ['input[name="password"]', '#password', 'input[type="password"]']:
        try:
            pwd = driver.find_element(By.CSS_SELECTOR, sel)
            if pwd.is_displayed():
                break
            pwd = None
        except:
            continue

    if not uname or not pwd:
        raise Exception("找不到登录输入框")

    uname.clear()
    uname.send_keys(cfg['username'])
    pwd.clear()
    pwd.send_keys(cfg['password'])
    log.info("已填写账号密码")

    captcha_input = _find_captcha_input(driver)
    if captcha_input:
        log.info("检测到验证码，自动识别中...")
        for attempt in range(15):
            ci = _find_captcha_input(driver)
            if not ci:
                break
            img_b64 = _get_captcha_b64(driver)
            if not img_b64:
                time.sleep(1)
                continue
            code = _ocr(img_b64, cfg)
            if not code:
                _refresh_captcha(driver)
                time.sleep(1)
                continue
            log.info(f"  验证码: {code} ({attempt+1}/15)")
            ci.clear()
            ci.send_keys(code)
            time.sleep(0.3)
            _click_login_btn(driver)
            time.sleep(3)
            if 'yuding' in driver.current_url and 'cas' not in driver.current_url:
                break
            if 'cas' in driver.current_url:
                page = driver.page_source
                if '密码' in page and '错误' in page:
                    raise Exception("密码错误!")
                _refresh_captcha(driver)
                time.sleep(1)
    else:
        _click_login_btn(driver)
        time.sleep(3)

    for _ in range(30):
        if 'yuding' in driver.current_url and 'cas' not in driver.current_url:
            break
        time.sleep(1)

    cookies = {}
    for c in driver.get_cookies():
        if 'yuding' in c.get('domain', ''):
            cookies[c['name']] = c['value']

    if not cookies.get('UserId'):
        raise Exception("登录失败 - 无UserId cookie")

    with open(COOKIE_PATH, 'w') as f:
        json.dump(cookies, f, indent=2)
    log.info("登录成功!")
    return cookies


def _find_captcha_input(driver):
    for sel in ['input[name="captchaCode"]', '#captchaCode', 'input[placeholder*="验证"]']:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed():
                return el
        except:
            pass
    return None


def _get_captcha_b64(driver):
    for sel in ['img[alt="验证码。"]', 'img[width="93"]', 'img[height="42"]']:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            path = os.path.join(SCRIPT_DIR, 'captcha.png')
            el.screenshot(path)
            with open(path, 'rb') as f:
                return base64.b64encode(f.read()).decode()
        except:
            pass
    return None


def _refresh_captcha(driver):
    for sel in ['img[alt="验证码。"]', 'img[width="93"]', 'img[height="42"]']:
        try:
            driver.find_element(By.CSS_SELECTOR, sel).click()
            return
        except:
            pass


def _click_login_btn(driver):
    for sel in ['button[type="submit"]', '.el-button--primary', 'input[type="button"][value*="登录"]']:
        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, sel):
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    return
        except:
            pass


def _ocr(img_b64, cfg):
    provider = cfg.get('captcha_provider', 'yunma')
    import requests
    try:
        if provider == 'chaojiying':
            return _ocr_chaojiying(img_b64, cfg)
        else:
            return _ocr_yunma(img_b64, cfg['yunma_token'])
    except:
        return None


def _ocr_chaojiying(img_b64, cfg):
    import requests
    r = requests.post('https://upload.chaojiying.net/Upload/Processing.php', data={
        'user': cfg['cjy_user'], 'pass': cfg['cjy_pass'],
        'softid': cfg['cjy_soft_id'], 'codetype': '1004',
        'file_base64': img_b64,
    }, timeout=15)
    result = r.json()
    if result.get('err_no') == 0:
        code = re.sub(r'[^a-zA-Z0-9]', '', result.get('pic_str', ''))
        log.info(f"  超级鹰: {code}")
        return code if len(code) >= 3 else None
    log.warning(f"  超级鹰失败: {result.get('err_str')}")
    return None


def _ocr_yunma(img_b64, token):
    import requests
    r = requests.post('http://api.jfbym.com/api/YmServer/customApi', json={
        'image': img_b64, 'type': '10110', 'token': token,
    }, timeout=15)
    data = r.json()
    result_str = ''
    if data.get('code') == 0:
        result_str = str(data.get('data', ''))
    elif data.get('code') == 10000:
        d = data.get('data')
        result_str = str(d.get('data', '')) if isinstance(d, dict) else str(d or '')
    clean = re.sub(r'[^a-zA-Z0-9]', '', result_str)
    return clean if len(clean) >= 3 else None


# ─── 预热 ───

def warmup(driver, date_index, time_period):
    driver.get(BOOKING_URL)
    time.sleep(5)
    driver.execute_script(f"getDateData('{date_index}')")
    time.sleep(2)
    driver.execute_script(f"getDataTime('{time_period}')")
    time.sleep(3)

    count = len(driver.find_elements(By.CSS_SELECTOR, 'li.col'))
    if count == 0:
        log.warning("格子数为0，重试...")
        for retry in range(3):
            driver.get(BOOKING_URL)
            time.sleep(3)
            driver.execute_script(f"getDateData('{date_index}')")
            time.sleep(2)
            driver.execute_script(f"getDataTime('{time_period}')")
            time.sleep(3)
            count = len(driver.find_elements(By.CSS_SELECTOR, 'li.col'))
            if count > 0:
                break
            log.warning(f"重试 {retry+1}/3 格子数仍为0")

    log.info(f"预热完成: {count} 个格子")
    return count


# ─── 扫描 + 规划 ───

def scan_available(driver):
    """扫描所有可选(kyd)格子"""
    js = """
    var results = [];
    var els = document.querySelectorAll('li.col');
    for (var i = 0; i < els.length; i++) {
        var div = els[i].querySelector('div');
        var dc = div ? div.className : '';
        if (dc.indexOf('kyd') >= 0) {
            var fn = els[i].getAttribute('fieldname') || '';
            var bt = els[i].getAttribute('begintime') || '';
            var et = els[i].getAttribute('endtime') || '';
            var cn = fn.replace('羽毛球', '');
            results.push({id: els[i].id, fn: fn, bt: bt, et: et, cn: cn});
        }
    }
    return results;
    """
    return driver.execute_script(js) or []


def build_plan(available):
    """
    构建抢场计划（返回要 chose 的格子列表）
    
    1. 8+11 的 15:00+16:00 -> 有几个选几个
    2. 相邻场 5+8 或 11+14 的 15:00+16:00
    3. 任意场号的 15:00+16:00，优先凑完整2小时
    4. 只剩一小时也抢
    """
    time_set = set(TARGET_SLOTS)
    target_slots = [s for s in available if s['bt'] in time_set]

    def pick_group(courts, tier_name):
        court_set = set(courts)
        matched = [s for s in target_slots if s['cn'] in court_set]
        if not matched:
            return None
        log.info(f"{tier_name}: {courts}, {len(matched)} 个时段")
        for s in matched:
            log.info(f"  -> {s['fn']} {s['bt']}-{s['et']}")
        return matched

    # 方案1: 8+11
    plan = pick_group(GROUP_BEST, "方案1")
    if plan:
        return plan

    # 方案2: 相邻 5+8
    plan = pick_group(GROUP_ADJACENT_A, "方案2")
    if plan:
        return plan

    # 方案3: 相邻 11+14
    plan = pick_group(GROUP_ADJACENT_B, "方案3")
    if plan:
        return plan

    # 方案4: 任意场号，优先完整2小时
    if target_slots:
        from collections import defaultdict
        by_court = defaultdict(list)
        for s in target_slots:
            by_court[s['cn']].append(s)
        # 优先凑齐两个时段的场号
        complete = []
        partial = []
        for cn in sorted(by_court.keys()):
            slots = sorted(by_court[cn], key=lambda s: s['bt'])
            times = {s['bt'] for s in slots}
            if times >= time_set:
                complete.extend(slots)
            else:
                partial.extend(slots)
        plan = complete if complete else partial
        log.info(f"方案4: 任意场, {len(plan)} 个时段")
        for s in plan:
            log.info(f"  -> {s['fn']} {s['bt']}-{s['et']}")
        return plan

    log.warning("没有任何可选时段!")
    return []


# ─── 抢场（集中选择，一次提交）───

def grab_batch(driver, plan):
    """
    一次性选中 plan 中所有格子，然后 onShareBooking → confirm → PayField
    返回 [(label, success, detail), ...]
    """
    results = []

    if not plan:
        return results

    # 1. 逐个 chose（纯页面内点击，不跳转）
    chosen = []
    for slot in plan:
        label = f"{slot['fn']} {slot['bt']}-{slot['et']}"
        try:
            driver.execute_script(f"chose(document.getElementById('{slot['id']}'));")
            time.sleep(0.2)
            alert_text = _dismiss_alert(driver)
            if alert_text:
                log.warning(f"  {label} chose被拒: {alert_text}")
                results.append((label, False, f"chose被拒: {alert_text}"))
            else:
                chosen.append(slot)
                log.info(f"  已选: {label}")
        except Exception as e:
            log.warning(f"  {label} chose异常: {e}")
            results.append((label, False, str(e)))

    if not chosen:
        log.error("没有任何格子成功 chose!")
        return results

    log.info(f"共选中 {len(chosen)} 个时段，提交中...")

    # 2. onShareBooking
    driver.execute_script("onShareBooking()")
    time.sleep(1.0)

    alert_text = _dismiss_alert(driver)
    if alert_text:
        log.error(f"onShareBooking被拒: {alert_text}")
        for s in chosen:
            results.append((f"{s['fn']} {s['bt']}-{s['et']}", False, f"onShareBooking被拒: {alert_text}"))
        return results

    if 'SelectShareMember' not in driver.current_url:
        err = f"未跳转SelectShareMember: {driver.current_url}"
        log.error(err)
        for s in chosen:
            results.append((f"{s['fn']} {s['bt']}-{s['et']}", False, err))
        return results

    # 3. 勾选同行人 + 确认
    _select_all_members(driver)
    confirm_btn = driver.find_element(By.CSS_SELECTOR, '.confirm-btn')
    confirm_btn.click()
    time.sleep(1.5)

    alert_text = _dismiss_alert(driver)
    if alert_text:
        log.error(f"确认被拒: {alert_text}")
        for s in chosen:
            results.append((f"{s['fn']} {s['bt']}-{s['et']}", False, f"确认被拒: {alert_text}"))
        return results

    if 'PayField' in driver.current_url:
        m = re.search(r'OID=([a-f0-9-]+)', driver.current_url)
        oid = m.group(1) if m else 'unknown'
        log.info(f"[OK] 全部成功! OID={oid}, 共{len(chosen)}个时段")
        for s in chosen:
            results.append((f"{s['fn']} {s['bt']}-{s['et']}", True, oid))
    else:
        err = f"未跳转PayField: {driver.current_url}"
        log.error(err)
        for s in chosen:
            results.append((f"{s['fn']} {s['bt']}-{s['et']}", False, err))

    return results


def _dismiss_alert(driver):
    try:
        alert = driver.switch_to.alert
        text = alert.text
        alert.dismiss()
        return text
    except:
        return None


def _select_all_members(driver):
    time.sleep(1)
    checkboxes = driver.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
    checked = 0
    for cb in checkboxes:
        try:
            if not cb.is_selected():
                cb.click()
                checked += 1
        except:
            driver.execute_script("arguments[0].click();", cb)
            checked += 1
    log.info(f"勾选 {checked} 个同行人")


# ─── 主流程 ───

def main():
    parser = argparse.ArgumentParser(description='HRBEU 智能抢场')
    parser.add_argument('--date', type=str, required=True, help='目标日期: 2026-05-08')
    parser.add_argument('--time', type=str, default='15:00', help='开始时间')
    parser.add_argument('--book-at', type=str, default=None, help='准点抢场时间，如 21:00')
    parser.add_argument('--warmup-minutes', type=int, default=10)
    parser.add_argument('--reuse-session', action='store_true')
    args = parser.parse_args()

    cfg = load_config()

    # 日期
    today = datetime.date.today()
    target_date = datetime.datetime.strptime(args.date, '%Y-%m-%d').date()
    date_index = (target_date - today).days

    # 时段
    hour = int(args.time.split(':')[0])
    time_period = '0' if hour < 12 else ('1' if hour < 17 else '2')

    log.info("=" * 50)
    log.info(f"目标: {target_date}")
    log.info(f"策略: 8+11 -> 5+8/11+14 -> 任意场")
    log.info(f"date_index={date_index}, period={time_period}")
    log.info("=" * 50)

    # 时间计算
    if args.book_at:
        bh, bm = map(int, args.book_at.split(':'))
        book_time = datetime.datetime.now().replace(hour=bh, minute=bm, second=0, microsecond=0)
        if book_time < datetime.datetime.now():
            book_time = datetime.datetime.now()
    else:
        book_time = datetime.datetime.now() + datetime.timedelta(seconds=5)

    warmup_time = book_time - datetime.timedelta(minutes=args.warmup_minutes)

    now = datetime.datetime.now()
    if warmup_time > now:
        wait_sec = (warmup_time - now).total_seconds()
        log.info(f"等待 {wait_sec/60:.1f} 分钟到预热时间 ({warmup_time:%H:%M})...")
        time.sleep(wait_sec)

    # Chrome
    log.info("启动 Chrome...")
    opts = Options()
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_experimental_option('excludeSwitches', ['enable-automation'])
    opts.add_argument('--window-size=480,720')
    driver = webdriver.Chrome(options=opts)

    try:
        # 登录
        if args.reuse_session and os.path.exists(COOKIE_PATH):
            log.info("复用cookie...")
            driver.get(BOOKING_URL)
            time.sleep(2)
            with open(COOKIE_PATH) as f:
                cookies = json.load(f)
            for name, value in cookies.items():
                driver.add_cookie({'name': name, 'value': value, 'domain': 'yuding.hrbeu.edu.cn'})
            driver.get(BOOKING_URL)
            time.sleep(2)
        else:
            login(driver, cfg)

        # 预热
        warmup(driver, date_index, time_period)

        # 等到抢场时间
        now = datetime.datetime.now()
        if book_time > now:
            wait_sec = (book_time - now).total_seconds()
            if wait_sec > 0.5:
                log.info(f"等待 {wait_sec:.1f}s 到 {book_time:%H:%M:%S}...")
                time.sleep(max(0, wait_sec - 0.5))
        now = datetime.datetime.now()
        if book_time > now:
            time.sleep((book_time - now).total_seconds())

        # ─── 抢! ───
        t0 = time.time()
        log.info(f"[{datetime.datetime.now():%H:%M:%S}] 开始抢场!")

        available = scan_available(driver)
        log.info(f"扫描到 {len(available)} 个可选时段")
        plan = build_plan(available)

        if not plan:
            log.error("无计划可执行!")
            results = []
        else:
            results = grab_batch(driver, plan)

        elapsed = time.time() - t0

        # 汇总
        log.info("=" * 50)
        log.info(f"抢场结束，耗时 {elapsed:.2f}s")
        success = sum(1 for _, ok, _ in results if ok)
        fail = sum(1 for _, ok, _ in results if not ok)
        log.info(f"成功: {success}, 失败: {fail}")
        for label, ok, detail in results:
            log.info(f"  {'[OK]' if ok else '[FAIL]'} {label} - {detail}")
        log.info("=" * 50)

    except Exception as e:
        log.error(f"异常: {e}")
        import traceback
        traceback.print_exc()
        try:
            driver.save_screenshot(os.path.join(SCRIPT_DIR, 'grab_error.png'))
        except:
            pass
    finally:
        time.sleep(2)
        driver.quit()
        log.info("浏览器已关闭")


if __name__ == '__main__':
    main()
