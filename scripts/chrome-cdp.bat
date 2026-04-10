@echo off
REM feedgrab Chrome CDP 启动脚本
REM 以远程调试模式启动 Chrome，feedgrab 通过 CDP 复用登录态，无需手动授权
REM
REM 用法：双击运行，或在终端执行 scripts\chrome-cdp.bat
REM 启动后正常使用 Chrome 登录知乎/飞书/金山文档等平台
REM feedgrab 设置 ZHIHU_CDP_ENABLED=true 即可自动连接

set CDP_PORT=9222
set CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe

REM 检查是否已有 Chrome 在运行
tasklist /FI "IMAGENAME eq chrome.exe" 2>NUL | find /I "chrome.exe" >NUL
if %ERRORLEVEL%==0 (
    echo [!] Chrome 已在运行。CDP 模式需要在启动时指定参数。
    echo     请先关闭所有 Chrome 窗口，再运行此脚本。
    echo.
    echo     或者手动在已运行的 Chrome 地址栏输入:
    echo     chrome://inspect/#devices
    pause
    exit /b 1
)

echo [feedgrab] 以 CDP 模式启动 Chrome (port=%CDP_PORT%)...
echo.
echo   启动后：
echo   1. 正常登录知乎、飞书、金山文档等平台
echo   2. feedgrab 会自动通过 CDP 复用你的登录态
echo   3. 无需手动点击授权确认
echo.

start "" "%CHROME_PATH%" ^
    --remote-debugging-port=%CDP_PORT% ^
    --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data" ^
    --restore-last-session

echo [OK] Chrome 已启动，CDP 端口: %CDP_PORT%
echo      feedgrab 配置: ZHIHU_CDP_ENABLED=true / FEISHU_CDP_ENABLED=true / KDOCS_CDP_ENABLED=true
