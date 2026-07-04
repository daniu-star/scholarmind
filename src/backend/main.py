"""
ScholarMind 应用入口
启动方式:
  python -m src.backend.main
  uvicorn src.backend.app:create_app --factory --host 0.0.0.0 --port 8000
"""
from src.backend.app import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
