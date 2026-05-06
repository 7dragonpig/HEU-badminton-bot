#!/usr/bin/env python3
"""
HRBEU 羽毛球场定时抢场脚本

用法:
  python auto_book.py --target "明天14:00 8号场"
  python auto_book.py --court 8 --time 14:00 --date tomorrow
  python auto_book.py --court 8 --time 14:00 --date 2026-05-08

流程:
  1. 提前10分钟启动Chrome，登录，加载页面
  2. 精确等到指定时间
  3. 快速执行 chose() → onShareBooking() → 确认下单 (~2-3秒)

配置: config.json
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
log = logging.getLogger("book")

BASE = 'https://yuding.hrbeu.edu.cn'


def load_config():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return json.load(f)


def login(driver, cfg):
    """Selenium CAS 登录，返回 cookies dict"""
    driver.get(f"{BASE}/User/UserChoose?LoginType=1")
    time.sleep(1)
    if 'cas' not in driver.current_url:
        driver.get(f"{BASE}/User/Login")
        time.sleep(1)

    wait = WebDriverWait(driver, 30)

    # Find username input
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

    # 验证码
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

            code = _ocr(img_b64, cfg['yunma_token'], cfg=cfg)
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

    # 等待跳转
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


def _ocr(img_b64, token, cfg=None):
    """验证码识别，根据 captcha_provider 选择平台"""
    provider = (cfg or {}).get('captcha_provider', 'yunma')
    import requests
    try:
        if provider == 'chaojiying':
            return _ocr_chaojiying(img_b64, cfg)
        else:
            return _ocr_yunma(img_b64, token)
    except:
        return None


def _ocr_chaojiying(img_b64, cfg):
    """超级鹰验证码识别"""
    import requests
    url = 'https://upload.chaojiying.net/Upload/Processing.php'
    data = {
        'user': cfg['cjy_user'],
        'pass': cfg['cjy_pass'],
        'softid': cfg['cjy_soft_id'],
        'codetype': '1004',  # 4位字母数字混合
        'file_base64': img_b64,
    }
    r = requests.post(url, data=data, timeout=15)
    result = r.json()
    # 返回格式: {"err_no":0, "err_str":"OK", "pic_id":"...", "pic_str":"abcd", "md5":"..."}
    if result.get('err_no') == 0:
        code = result.get('pic_str', '').strip()
        clean = re.sub(r'[^a-zA-Z0-9]', '', code)
        log.info(f"  超级鹰识别: {clean} (pic_id={result.get('pic_id','')})")
        return clean if len(clean) >= 3 else None
    else:
        log.warning(f"  超级鹰失败: err_no={result.get('err_no')}, err_str={result.get('err_str')}")
        return None


def _ocr_yunma(img_b64, token):
    """云码验证码识别"""
    import requests
    r = requests.post('http://api.jfbym.com/api/YmServer/customApi', json={
        'image': img_b64, 'type': '10110', 'token': token,
    }, timeout=15)
    data = r.json()
    code_val = data.get('code', -1)
    result_str = ''
    if code_val == 0:
        d = data.get('data', '')
        result_str = str(d) if not isinstance(d, str) else d
    elif code_val == 10000:
        d = data.get('data')
        if isinstance(d, dict):
            result_str = str(d.get('data', ''))
        elif isinstance(d, str):
            result_str = d
    clean = re.sub(r'[^a-zA-Z0-9]', '', result_str)
    return clean if len(clean) >= 3 else None


def warmup(driver, date_index, time_period, venue_no='002', ft_no='YMQ001'):
    """预热：加载预订页面，选好日期和时段，等待抢场"""
    url = f'{BASE}/Views/Field/FieldOrder.html?VenueNo={venue_no}&FieldTypeNo={ft_no}'
    driver.get(url)
    time.sleep(5)
    log.info(f"预订页已加载: {driver.current_url}")

    # 切换到目标日期
    driver.execute_script(f"getDateData('{date_index}')")
    time.sleep(2)

    # 切换到目标时段
    driver.execute_script(f"getDataTime('{time_period}')")
    time.sleep(3)

    # 验证数据已加载，格子数为0则重试
    count = len(driver.find_elements(By.CSS_SELECTOR, 'li.col'))
    if count == 0:
        log.warning(f"格子数为0，重试加载...")
        for retry in range(3):
            driver.get(url)
            time.sleep(3)
            driver.execute_script(f"getDateData('{date_index}')")
            time.sleep(2)
            driver.execute_script(f"getDataTime('{time_period}')")
            time.sleep(3)
            count = len(driver.find_elements(By.CSS_SELECTOR, 'li.col'))
            if count > 0:
                break
            log.warning(f"重试 {retry+1}/3 格子数仍为0")
    log.info(f"已加载 {count} 个时段格子 (date={date_index}, period={time_period})")
    return count


def grab(driver, court_name, begin_time):
    """执行抢场: chose → onShareBooking → 确认下单"""
    # 找到目标场地
    li_elements = driver.find_elements(By.CSS_SELECTOR, 'li.col')
    target = None
    for li in li_elements:
        fn = li.get_attribute('fieldname') or ''
        bt = li.get_attribute('begintime') or ''
        if court_name in fn and begin_time in bt:
            div = li.find_element(By.TAG_NAME, 'div')
            dc = div.get_attribute('class')
            if 'kyd' in dc:
                target = li
                log.info(f"找到可预订: {fn} {bt}-{li.get_attribute('endtime')}")
            else:
                log.warning(f"找到但不可预订: {fn} {bt} class={dc}")
            break

    if not target:
        # 备选：找同一场地的其他状态
        for li in li_elements:
            fn = li.get_attribute('fieldname') or ''
            bt = li.get_attribute('begintime') or ''
            if court_name in fn and begin_time in bt:
                log.warning(f"场地存在但状态异常: {fn} {bt}")
                break
        raise Exception(f"场地 {court_name} {begin_time} 不可用!")

    # Step 1: chose()
    el_id = target.get_attribute('id')
    driver.execute_script(f"chose(document.getElementById('{el_id}'));")
    time.sleep(0.5)

    # 验证选中
    div = target.find_element(By.TAG_NAME, 'div')
    if 'myd' not in div.get_attribute('class'):
        raise Exception("chose() 失败 - 未选中")

    # Step 2: onShareBooking()
    driver.execute_script("onShareBooking()")
    time.sleep(2)

    if 'SelectShareMember' not in driver.current_url:
        raise Exception("onShareBooking() 后未跳转到同行人页面")

    # Step 3: 确认下单
    confirm_btn = driver.find_element(By.CSS_SELECTOR, '.confirm-btn')
    confirm_btn.click()
    time.sleep(3)

    if 'PayField' in driver.current_url:
        # 提取 OID
        import re
        m = re.search(r'OID=([a-f0-9-]+)', driver.current_url)
        oid = m.group(1) if m else 'unknown'
        log.info(f"抢场成功! OID: {oid}")
        return oid
    else:
        raise Exception(f"下单后未跳转到支付页: {driver.current_url}")


def grab_any(driver, begin_time):
    """找任意可用的场地抢"""
    li_elements = driver.find_elements(By.CSS_SELECTOR, 'li.col')
    for li in li_elements:
        bt = li.get_attribute('begintime') or ''
        if begin_time not in bt:
            continue
        div = li.find_element(By.TAG_NAME, 'div')
        dc = div.get_attribute('class')
        if 'kyd' in dc:
            fn = li.get_attribute('fieldname') or ''
            et = li.get_attribute('endtime') or ''
            log.info(f"找到任意空场: {fn} {bt}-{et}")
            el_id = li.get_attribute('id')
            driver.execute_script(f"chose(document.getElementById('{el_id}'));")
            time.sleep(0.5)
            div = li.find_element(By.TAG_NAME, 'div')
            if 'myd' not in div.get_attribute('class'):
                continue
            driver.execute_script("onShareBooking()")
            time.sleep(2)
            if 'SelectShareMember' not in driver.current_url:
                continue
            confirm_btn = driver.find_element(By.CSS_SELECTOR, '.confirm-btn')
            confirm_btn.click()
            time.sleep(3)
            if 'PayField' in driver.current_url:
                m = re.search(r'OID=([a-f0-9-]+)', driver.current_url)
                oid = m.group(1) if m else 'unknown'
                log.info(f"抢场成功! {fn} OID: {oid}")
                return oid
    raise Exception(f"没有找到 {begin_time} 的任何空场!")


def main():
    parser = argparse.ArgumentParser(description='HRBEU 羽毛球场定时抢场')
    parser.add_argument('--court', type=str, required=True, help='场地号，如 8, 11, 13')
    parser.add_argument('--fallback-courts', type=str, default='any',
                        help='备选场地，逗号分隔，如 "8,any" 表示先抢8号再抢任意空场 (默认: any)')
    parser.add_argument('--time', type=str, required=True, help='开始时间，如 14:00, 19:00')
    parser.add_argument('--date', type=str, default='tomorrow',
                        help='日期: tomorrow=明天, today=今天, 或 2026-05-08')
    parser.add_argument('--book-at', type=str, default=None,
                        help='抢场时间，如 21:00 (默认立即执行)')
    parser.add_argument('--warmup-minutes', type=int, default=10,
                        help='提前多少分钟预热 (默认10分钟)')
    parser.add_argument('--reuse-session', action='store_true',
                        help='复用已保存的cookie，跳过登录')
    args = parser.parse_args()

    cfg = load_config()

    # 解析日期
    today = datetime.date.today()
    if args.date == 'tomorrow':
        target_date = today + datetime.timedelta(days=1)
        date_index = 1
    elif args.date == 'today':
        target_date = today
        date_index = 0
    else:
        target_date = datetime.datetime.strptime(args.date, '%Y-%m-%d').date()
        date_index = (target_date - today).days

    # 解析时段
    hour = int(args.time.split(':')[0])
    if hour < 12:
        time_period = '0'  # 上午
    elif hour < 17:
        time_period = '1'  # 下午
    else:
        time_period = '2'  # 晚上

    # 处理场地名：输入 "8" → "羽毛球08"，输入 "13" → "羽毛球13"
    court_num = args.court.zfill(2) if len(args.court) <= 2 else args.court
    court_name = f"羽毛球{court_num}"

    # 构建尝试列表: ["羽毛球11", "羽毛球08", "any"]
    try_list = [court_name]
    for fb in args.fallback_courts.split(','):
        fb = fb.strip()
        if fb == 'any':
            try_list.append('any')
        elif fb:
            fb_num = fb.zfill(2) if len(fb) <= 2 else fb
            try_list.append(f"羽毛球{fb_num}")
    log.info(f"尝试顺序: {' → '.join(try_list)}")

    log.info("=" * 50)
    log.info(f"目标: {target_date} {args.time} {court_name}")
    log.info(f"date_index={date_index}, time_period={time_period}")
    log.info("=" * 50)

    # 计算预热时间 (book_at 用今天的日期，不是目标日期)
    if args.book_at:
        book_hour, book_min = map(int, args.book_at.split(':'))
        today_dt = datetime.datetime.now()
        book_time = today_dt.replace(hour=book_hour, minute=book_min, second=0, microsecond=0)
        # 如果 book_time 已过，说明已经过了抢场时间，立即执行
        if book_time < today_dt:
            log.warning(f"book_at {args.book_at} 已过，立即执行")
            book_time = today_dt
    else:
        book_time = datetime.datetime.now() + datetime.timedelta(seconds=5)

    warmup_time = book_time - datetime.timedelta(minutes=args.warmup_minutes)

    # 等待到预热时间
    now = datetime.datetime.now()
    if warmup_time > now:
        wait_sec = (warmup_time - now).total_seconds()
        log.info(f"等待 {wait_sec/60:.1f} 分钟到预热时间 ({warmup_time:%H:%M})...")
        time.sleep(wait_sec)

    # 启动 Chrome
    log.info("启动 Chrome...")
    opts = Options()
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_experimental_option('excludeSwitches', ['enable-automation'])
    opts.add_argument('--window-size=480,720')
    driver = webdriver.Chrome(options=opts)

    try:
        # 登录
        if args.reuse_session and os.path.exists(COOKIE_PATH):
            log.info("复用已保存的cookie，跳过登录...")
            # 先打开目标域名（任意页面即可，用于设置cookie）
            driver.get(f'{BASE}/Views/Field/FieldOrder.html?VenueNo=002&FieldTypeNo=YMQ001')
            time.sleep(2)
            with open(COOKIE_PATH) as f:
                cookies = json.load(f)
            for name, value in cookies.items():
                driver.add_cookie({'name': name, 'value': value, 'domain': 'yuding.hrbeu.edu.cn'})
            log.info(f"已加载 {len(cookies)} 个cookie")
            # 刷新页面让cookie生效
            driver.get(f'{BASE}/Views/Field/FieldOrder.html?VenueNo=002&FieldTypeNo=YMQ001')
            time.sleep(2)
            log.info(f"cookie刷新后页面: {driver.current_url}")
        else:
            log.info("登录中...")
            cookies = login(driver, cfg)

        # 预热
        log.info("预热预订页面...")
        warmup(driver, date_index, time_period)

        # 等待到抢场时间
        now = datetime.datetime.now()
        if book_time > now:
            wait_sec = (book_time - now).total_seconds()
            # 提前 3 秒醒来，刷新页面确保状态新鲜
            actual_wait = max(0, wait_sec - 3)
            if actual_wait > 0:
                log.info(f"页面就绪，等待 {actual_wait:.1f} 秒到 {book_time:%H:%M:%S}...")
                time.sleep(actual_wait)

            # 精确等待到整点前刷新页面，避免等待期间session过期
            log.info("刷新页面确保状态新鲜...")
            driver.get(f'{BASE}/Views/Field/FieldOrder.html?VenueNo=002&FieldTypeNo=YMQ001')
            time.sleep(2)
            driver.execute_script(f"getDateData('{date_index}')")
            time.sleep(1)
            driver.execute_script(f"getDataTime('{time_period}')")
            time.sleep(1)
            count = len(driver.find_elements(By.CSS_SELECTOR, 'li.col'))
            log.info(f"刷新后格子数: {count}")

        # 精确等待到整点
        now = datetime.datetime.now()
        if book_time > now:
            time.sleep((book_time - now).total_seconds())

        # 抢!
        t0 = time.time()
        log.info(f"[{datetime.datetime.now():%H:%M:%S}] 开始抢场!")
        oid = None

        for i, court in enumerate(try_list):
            is_last = (i == len(try_list) - 1)
            try:
                if court == 'any':
                    oid = grab_any(driver, args.time)
                else:
                    oid = grab(driver, court, args.time)
                break  # 成功了就停
            except Exception as e:
                log.warning(f"  {court} 失败: {e}")
                if not is_last:
                    # 快速重试：同页刷新数据，不重新加载整个页面
                    log.info(f"  → 尝试下一个: {try_list[i+1]}")
                    next_court = try_list[i+1]
                    if next_court == 'any':
                        # any模式需要完整数据，快速刷新
                        driver.execute_script(f"getDataTime('{time_period}')")
                        time.sleep(2)
                    else:
                        # 指定场地只需要重新读DOM，不需要重载
                        time.sleep(0.5)

        if oid:
            elapsed = time.time() - t0
            log.info(f"抢场完成! 耗时 {elapsed:.2f}s, OID: {oid}")
        else:
            log.error("全部尝试失败!")

    except Exception as e:
        log.error(f"失败: {e}")
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
