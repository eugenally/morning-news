@echo off
REM 굿모닝 브리핑 실행 래퍼 (윈도우 작업 스케줄러에서 이 파일을 실행)
cd /d "%~dp0"
"C:\01Developorkits\Python\Python314\python.exe" "%~dp0morning_feed.py" >> "%~dp0feed.log" 2>&1
