"""成功绑定本机演示端口后才打开浏览器，避免误用仍在运行的旧后端。"""

import threading
import webbrowser

URL = "http://127.0.0.1:5000"


def run_demo(app, *, open_browser=False, server_factory=None):
    if server_factory is None:
        from werkzeug.serving import make_server

        server_factory = make_server
    try:
        server = server_factory("127.0.0.1", 5000, app, threaded=True)
    except (OSError, SystemExit):
        print(
            "[错误] 后端未能监听本机5000端口，浏览器未打开。请关闭旧的后端窗口或占用该端口的程序，再重新启动。"
        )
        return 1

    print(f"养老服务平台演示后端已启动 → {URL}")
    print(
        "演示账号（密码均为 123456）：shequ / jiashu / jiashu2 / hugong / jigou / jianguan"
    )
    browser = None
    try:
        if open_browser:
            browser = threading.Timer(0.5, webbrowser.open, args=(URL,))
            browser.daemon = True
            browser.start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if browser:
            browser.cancel()
        server.server_close()
    return 0
