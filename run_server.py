import uvicorn
import os
import sys

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

    print("=================================================================")
    print(" Vacation Scheduling Multi-Agent System (MAX + Dashboard)")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8000))
    print(f" Starting FastAPI Server on http://{host}:{port}")
    print("=================================================================")
    uvicorn.run("backend.main:app", host=host, port=port, reload=False)

