@echo off
rem 本文件必须保持 GBK(ANSI) 编码 + CRLF 换行，中文 cmd 才能正确解析
cd /d "%~dp0"
echo ================================================
echo   社区居家养老智慧服务平台 - 演示一键启动
echo ================================================
echo.

where mysql >nul 2>nul
if errorlevel 1 (
  echo [错误] 找不到 mysql 命令，请确认已安装 MySQL 并加入 PATH
  pause & exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 找不到 python 命令
  pause & exit /b 1
)

python -c "import flask, pymysql, cryptography" >nul 2>nul
if errorlevel 1 (
  echo [提示] 缺少依赖，正在安装 flask pymysql ...
  python -m pip install -r requirements.txt
  if errorlevel 1 ( echo [错误] 依赖安装失败 & pause & exit /b 1 )
)

rem 一键演示的mysql客户端、检查脚本和Flask必须连接同一个本机演示库
set "MYSQL_HOST=127.0.0.1"
set "MYSQL_PORT=3306"
set "MYSQL_USER=root"
set "MYSQL_DB=elder_care"
set "MYSQL_PWD="
set /p "MYSQL_PWD=请输入本机 MySQL root 密码:"

set "RESET="
set /p RESET=是否重置演示数据库？会清空重建 elder_care 库 (y/N):
if /i "%RESET%"=="y" (
  echo 正在导入数据库脚本...
  for %%f in (sql\01_schema.sql sql\02_seed.sql sql\03_views.sql sql\04_procs_triggers.sql) do (
    mysql -h127.0.0.1 -P3306 --protocol=TCP -uroot --default-character-set=utf8mb4 < "%%f"
    if errorlevel 1 ( echo [错误] %%f 导入失败，请检查密码 & pause & exit /b 1 )
  )
  echo 数据库初始化完成。
)

echo 正在检查数据库，必要时升级结构并保留已有数据...
python src\backend\prepare_database.py
if errorlevel 1 (
  echo [错误] 数据库尚未就绪，已停止启动。请根据上方提示处理后重试。
  pause & exit /b 1
)

echo 正在启动后端，浏览器将自动打开 http://127.0.0.1:5000 ...
start "" cmd /c "timeout /t 2 /nobreak >nul & start "" http://127.0.0.1:5000"
cd src\backend
python app.py
