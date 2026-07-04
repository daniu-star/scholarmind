@echo off
chcp 65001 >nul
title CNKI Auto Download - 400 Papers

echo ========================================
echo   CNKI Auto Paper Download
echo ========================================
echo.
echo This will open 400 papers for download.
echo Make sure your browser has CNKI login cookies!
echo.
echo Press any key to start...
pause >nul

echo.
echo Opening download page in Chrome...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --new-window --start-maximized "file:///c:/Users/13067/Desktop/AI产品/cnki-downloader/downloads/all_papers_download.html"

echo.
echo Opening in Edge (backup)...
start msedge "file:///c:/Users/13067/Desktop/AI产品/cnki-downloader/downloads/all_papers_download.html"

echo.
echo ========================================
echo If you DON'T see the download page:
echo   1. Open Chrome manually
echo   2. Go to File - Open (Ctrl+O)
echo   3. Open: c:\Users\13067\Desktop\AI产品\cnki-downloader\downloads\all_papers_download.html
echo   4. Press S to start auto-download
echo ========================================
echo.
pause
