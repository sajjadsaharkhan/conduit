"""Admin authentication: password hashing and session/token validation."""
import os
import secrets
import bcrypt
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional

def _load_secret() -> str:
    """JWT_SECRET from env, else a secret generated once and kept next to the database.

    A secret generated per process would log every admin out on each restart or deploy.
    """
    if os.environ.get("JWT_SECRET"):
        return os.environ["JWT_SECRET"]
    path = os.path.join(os.path.dirname(os.environ.get("DATABASE_PATH", "/data/conduit.db")) or ".", ".jwt_secret")
    try:
        with open(path) as f:
            secret = f.read().strip()
        if secret:
            return secret
    except FileNotFoundError:
        pass
    secret = secrets.token_hex(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secret)
    except OSError:
        pass  # read-only data dir: sessions just won't survive restarts
    return secret


SECRET_KEY = _load_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
