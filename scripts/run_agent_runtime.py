"""启动本地配置的研究服务；不改变生产环境或冻结预测默认模型。"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--env-file", default=str(ROOT / ".env.runtime.local"))
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    import uvicorn
    uvicorn.run("backend.api.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()

