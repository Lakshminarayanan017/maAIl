stop-session:
	Get-NetTCPConnection -LocalPort 8000, 5173 -ErrorAction SilentlyContinue | `
    Select-Object -ExpandProperty OwningProcess -Unique | `
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }

start-backend:
	Start-Process -FilePath "c:\Users\Welcome\Desktop\maAil\backend\.venv\Scripts\python.exe" `
    -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--reload" `
    -WorkingDirectory "c:\Users\Welcome\Desktop\maAil\backend" -WindowStyle Hidden
start-frontend:
	Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c","npm run dev" `
    -WorkingDirectory "c:\Users\Welcome\Desktop\maAil\frontend" -WindowStyle Hidden