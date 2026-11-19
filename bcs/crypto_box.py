"""
Шифрование данных портфеля тем же ключом, что и страницы сайта.

Схема совпадает с build_protected.js:
  ключ = PBKDF2-HMAC-SHA256(f"{login}:{password}", salt, 600_000 итераций, 32 байта)
  шифротекст = IV(12) || AES-256-GCM(plaintext) || tag(16), дальше base64.

Соль НЕ генерируется заново, а берётся из уже собранных страниц (в оболочке входа
она лежит в открытом виде: var SALT = '...'). Иначе ключ получится другим, и браузер
не расшифрует файл тем ключом, который сохранён в sessionStorage['mx_k'].
Если MX_LOGIN/MX_PASSWORD не заданы или соль не найдена — пишем открытый JSON.
"""

import base64
import hashlib
import json
import os
import re

ITER = 600_000
_SALT_RE = re.compile(r"var SALT = '([^']+)'")


def find_salt(repo_root) -> bytes | None:
    """Ищет соль в собранных страницах (index.html и т.п.) в корне репозитория."""
    for name in ("index.html", "portfolio.html", "bonds.html", "news.html"):
        p = repo_root / name
        if p.exists():
            m = _SALT_RE.search(p.read_text(encoding="utf-8", errors="ignore"))
            if m:
                return base64.b64decode(m.group(1))
    return None


def encrypt_payload(obj: dict, login: str, password: str, salt: bytes) -> str:
    """dict -> base64(iv + шифротекст + тег), совместимо с WebCrypto AES-GCM."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.pbkdf2_hmac("sha256", f"{login}:{password}".encode("utf-8"), salt, ITER)
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode("utf-8"), None)
    return base64.b64encode(iv + ct).decode("ascii")


def write_json_or_encrypted(obj: dict, path, repo_root=None) -> str:
    """Пишет obj в path. Возвращает 'encrypted' или 'plain'."""
    login = os.environ.get("MX_LOGIN", "")
    password = os.environ.get("MX_PASSWORD", "")
    path.parent.mkdir(parents=True, exist_ok=True)
    if login and password:
        salt = find_salt(repo_root or path.parent.parent)
        if salt:
            path.write_text(encrypt_payload(obj, login, password, salt), encoding="utf-8")
            return "encrypted"
        print("ПРЕДУПРЕЖДЕНИЕ: соль не найдена в собранных *.html — пишу открытый JSON")
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return "plain"
