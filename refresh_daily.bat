@echo off
rem Daily refresh of the job board: download every feed, rebuild, check, deploy to Cloudflare.
rem Run by hand (double-click) or from Windows Task Scheduler. Details are written to logs\refresh-DATE.txt.
cd /d "%~dp0"
if not exist logs mkdir logs
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -u pipeline\refresh.py >> logs\task_output.txt 2>&1
