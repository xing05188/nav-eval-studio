"""口令哈希与访问令牌。

口令：PBKDF2-HMAC-SHA256，随机 16 字节盐，迭代次数由配置决定。
令牌：base64url(payload).base64url(hmac_sha256(payload))，无第三方依赖。
密钥首次启动生成并保存到 storage/secret.key，重启后令牌仍有效。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from .response import UNAUTHORIZED, AppError

_SECRET: bytes | None = None
_ITERATIONS = 200000


def init_secret(secret_file: Path) -> bytes:
    """初始化签名密钥，文件不存在则生成。"""
    global _SECRET
    if secret_file.exists():
        _SECRET = secret_file.read_bytes()
    else:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        _SECRET = secrets.token_bytes(32)
        secret_file.write_bytes(_SECRET)
        try:
            os.chmod(secret_file, 0o600)
        except OSError:
            pass
    return _SECRET


def set_iterations(iterations: int) -> None:
    global _ITERATIONS
    _ITERATIONS = max(10000, int(iterations))


def _secret() -> bytes:
    if _SECRET is None:
        raise RuntimeError("签名密钥尚未初始化")
    return _SECRET


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password: str, password_hash: str, salt_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return hmac.compare_digest(digest.hex(), password_hash)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def create_token(user_id: int, username: str, role: str, ttl_hours: int) -> str:
    now = int(time.time())
    payload = {
        "uid": user_id,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + ttl_hours * 3600,
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64encode(signature)}"


def decode_token(token: str) -> dict:
    """校验并解析令牌，失败抛 1002。"""
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise AppError(UNAUTHORIZED, "令牌格式错误") from exc

    expected = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
    try:
        provided = _b64decode(signature)
    except Exception as exc:  # noqa: BLE001 - 解码失败一律视为非法令牌
        raise AppError(UNAUTHORIZED, "令牌签名非法") from exc
    if not hmac.compare_digest(expected, provided):
        raise AppError(UNAUTHORIZED, "令牌签名校验失败")

    try:
        payload = json.loads(_b64decode(body))
    except Exception as exc:  # noqa: BLE001
        raise AppError(UNAUTHORIZED, "令牌内容损坏") from exc

    if int(payload.get("exp", 0)) < int(time.time()):
        raise AppError(UNAUTHORIZED, "登录已过期，请重新登录")
    return payload
