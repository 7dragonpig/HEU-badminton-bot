"""同时抢两个时段，共享cookie只登录一次

流程:
  1. 第一个Chrome: 登录+预热+等到准点抢时段1
  2. 第二个Chrome: 复用cookie+预热+等到准点抢时段2
  3. 两个并行等，21:00同时抢

用法:
  python book_both.py --book-at 21:00 --date 2026-05-08 --times 15:00,16:00
"""
import subprocess, sys, threading, argparse, os, time, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_PATH = os.path.join(SCRIPT_DIR, 'session.json')

def wait_for_cookie(timeout=120):
    """等待cookie文件出现（由第一个进程的登录创建）"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(COOKIE_PATH):
            # 等文件写完
            time.sleep(0.5)
            try:
                with open(COOKIE_PATH) as f:
                    d = json.load(f)
                if d.get('UserId'):
                    return True
            except:
                pass
        time.sleep(1)
    return False

def run_first(court, fb, t, date, book_at):
    """第一个进程：登录+抢场"""
    cmd = [sys.executable, 'auto_book.py',
           '--court', court, '--fallback-courts', fb,
           '--time', t, '--date', date,
           '--warmup-minutes', '2']
    if book_at:
        cmd += ['--book-at', book_at]
    print(f"[{t}] 启动(带登录)...")
    r = subprocess.run(cmd, cwd=SCRIPT_DIR)
    print(f"[{t}] 退出码: {r.returncode}")

def run_second(court, fb, t, date, book_at):
    """第二个进程：等cookie就绪后启动，跳过登录"""
    print(f"[{t}] 等待cookie...")
    if not wait_for_cookie():
        print(f"[{t}] 等待cookie超时!")
        return
    print(f"[{t}] cookie就绪，启动抢场...")
    cmd = [sys.executable, 'auto_book.py',
           '--court', court, '--fallback-courts', fb,
           '--time', t, '--date', date,
           '--warmup-minutes', '2',
           '--reuse-session']  # 复用已有cookie
    if book_at:
        cmd += ['--book-at', book_at]
    r = subprocess.run(cmd, cwd=SCRIPT_DIR)
    print(f"[{t}] 退出码: {r.returncode}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--book-at', type=str, default=None, help='准点抢场时间，如 21:00')
    parser.add_argument('--date', type=str, required=True, help='目标日期')
    parser.add_argument('--times', type=str, default='15:00,16:00', help='时段，逗号分隔')
    parser.add_argument('--court', type=str, default='8', help='优先场地')
    parser.add_argument('--fallback', type=str, default='11,any', help='备选场地')
    args = parser.parse_args()

    times = [t.strip() for t in args.times.split(',')]
    if len(times) < 2:
        # 只有一个时段，直接跑
        run_first(args.court, args.fallback, times[0], args.date, args.book_at)
        return

    # 第一个时段：带登录
    t1 = threading.Thread(target=run_first,
                          args=(args.court, args.fallback, times[0], args.date, args.book_at))
    # 第二个时段：等cookie后启动
    t2 = threading.Thread(target=run_second,
                          args=(args.court, args.fallback, times[1], args.date, args.book_at))

    t2.start()  # 先启动等待线程
    t1.start()  # 再启动登录线程

    t1.join()
    t2.join()
    print("全部完成!")

if __name__ == '__main__':
    main()
