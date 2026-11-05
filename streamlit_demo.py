"""云端公开体验入口。本地完整版本仍使用 app.py。"""
import os
import runpy
from pathlib import Path
os.environ["COURSEMATE_PUBLIC_DEMO"] = "true"
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
