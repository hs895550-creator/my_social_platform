
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os

app = FastAPI()
os.makedirs("static_test", exist_ok=True)
try:
    app.mount("/static", StaticFiles(directory="static_test"), name="static")
    print("Mount success")
except Exception as e:
    print(f"Mount failed: {e}")
