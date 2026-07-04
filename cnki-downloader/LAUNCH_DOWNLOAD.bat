@echo off
chcp 65001 >nul
title CNKI Auto Download

echo ==========================================
echo   CNKI Auto-Download Launcher
echo ==========================================
echo.
echo This launches Chrome with the auto-click extension.
echo The V2 download page opens automatically.
echo.
echo Press S on the page to start batch downloading.
echo Each paper will auto-download PDF!
echo.
echo Make sure your browser has CNKI cookies!
echo ==========================================
echo.
pause

start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --load-extension="c:\Users\13067\Desktop\AI产品\cnki-downloader\extension" --new-window "file:///c:/Users/13067/Desktop/AI产品/cnki-downloader/downloads/all_papers_v2.html"

echo.
echo Chrome launched! Check the browser window.
echo.
pause
