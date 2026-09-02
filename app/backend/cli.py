from __future__ import annotations

import argparse

import uvicorn

from app.backend.config import DEFAULT_PORTS, VALID_ROLES, Settings
from app.backend.main import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动双角色实时客服后端")
    parser.add_argument("--role", required=True, choices=sorted(VALID_ROLES))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    expected_port = DEFAULT_PORTS[args.role]
    if args.port is not None and args.port != expected_port:
        parser.error(f"{args.role} 入口固定使用端口 {expected_port}")
    args.port = expected_port
    return args


def main() -> None:
    args = parse_args()
    settings = Settings.from_env(role=args.role)
    uvicorn.run(create_app(settings), host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
