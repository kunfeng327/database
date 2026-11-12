@echo off
rem 本文件必须保持 GBK(ANSI) 编码 + CRLF 换行，中文 cmd 才能正确解析
cd /d %~dp0
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

python -c "import flask, pymysql" >nul 2>nul
if errorlevel 1 (
  echo [提示] 缺少依赖，正在安装 flask pymysql ...
  pip install flask pymysql
  if errorlevel 1 ( echo [错误] 依赖安装失败 & pause & exit /b 1 )
)

set /p MP=请输入 MySQL root 密码:
set "MYSQL_PWD=%MP%"

set /p RESET=是否重置演示数据库？会清空重建 elder_care 库 (y/N):
if /i "%RESET%"=="y" (
  echo 正在导入数据库脚本...
  for %%f in (sql\01_schema.sql sql\02_seed.sql sql\03_views.sql sql\04_procs_triggers.sql) do (
    mysql -h127.0.0.1 -uroot --default-character-set=utf8mb4 < "%%f"
    if errorlevel 1 ( echo [错误] %%f 导入失败，请检查密码 & pause & exit /b 1 )
  )
  echo 数据库初始化完成。
)

echo 正在启动后端，浏览器将自动打开 http://127.0.0.1:5000 ...
start "" cmd /c "timeout /t 2 /nobreak >nul & start "" http://127.0.0.1:5000"
cd src\backend
python app.py
