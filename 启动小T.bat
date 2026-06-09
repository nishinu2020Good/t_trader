@echo off
title 小T — 做T自动驾驶
echo ===============================
echo   小T 正在启动...
echo   窗口1: 进程守护 (后台)
echo   窗口2: 实时仪表盘 (前台)
echo ===============================
echo.
echo   仪表盘每3秒刷新，看到数据就说明跑起来了
echo   关闭此窗口 = 停止小T
echo.
echo   启动中...
start "小T-仪表盘" cmd /k "python C:\Users\Administrator\Desktop\t_trader\dashboard.py"
python C:\Users\Administrator\Desktop\t_trader\watchdog.py
