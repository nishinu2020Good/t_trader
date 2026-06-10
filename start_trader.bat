@echo off
cd /d "C:\Users\Administrator\Desktop\t_trader"
echo ============================================
echo   小T 交易系统启动
echo   %date% %time%
echo ============================================
echo.

REM 先启动全市场扫描引擎 (后台)
echo [1/2] 启动全市场扫描引擎...
start /B "screener" python screener.py > screener_output.log 2>&1
timeout /t 3 /nobreak >nul
echo   扫描引擎已启动 (PID检查: tasklist /fi "WINDOWTITLE eq screener")

REM 等待首次扫描完成
echo   等待首次全市场扫描 (~20秒)...
timeout /t 20 /nobreak >nul

REM 启动实时驾驶舱 (后台)
echo [2/2] 启动实时驾驶舱...
start /B "cockpit" python cockpit.py > cockpit_output.log 2>&1
timeout /t 2 /nobreak >nul
echo   驾驶舱已启动

echo.
echo ============================================
echo   系统就绪
echo   扫描引擎: 全市场9999只, 每5分钟刷新
echo   驾驶舱:   持仓+TOP15候选, 每10秒刷新
echo   输出:     status.json + candidates.json
echo ============================================
exit /b
