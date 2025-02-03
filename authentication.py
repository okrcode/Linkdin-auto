from datetime import datetime, timedelta
from typing import Optional

from database import get_db, get_user_collection
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from models import Token

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

collection = get_db()


security = HTTPBearer()


class Auth0HTTPBearer(HTTPBearer):
    async def __call__(self, request: Request):
        return await super().__call__(request)


class AuthCustom:
    def __init__(self):
        self.implicit_scheme = None

    def get_user(
        self,
        creds: HTTPAuthorizationCredentials = Depends(
            Auth0HTTPBearer(auto_error=False)
        ),
    ):
        if creds:
            token = creds.credentials
            try:
                # Verify the token
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                email = payload.get("email")
                if email is None:
                    raise HTTPException(
                        status_code=401, detail="Email not found in token"
                    )
                return {"email": email}
            except JWTError:
                raise HTTPException(status_code=401, detail="Invalid token")
        else:
            raise HTTPException(status_code=401, detail="Token not provided")


auth_user = AuthCustom()

SECRET_KEY = "gyt"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(email: str, password: str):
    user_collection = get_user_collection()
    user = user_collection.find_one({"email": email})
    if not user or not verify_password(password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user


def create_access_token(
    user_id: str, email: str, expires_delta: Optional[timedelta] = None
):
    to_encode = {"id": user_id, "email": email}

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user(token: HTTPAuthorizationCredentials = Depends(security)) -> Token:
    credentials_exception = HTTPException(
        status_code=401,
        detail="Unauthorized User!",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_exception

    try:
        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("email")
        if email is None:
            raise credentials_exception
        token_data = Token(
            access_token=token.credentials, token_type="bearer", email=email
        )
        return token_data
    except JWTError:
        raise credentials_exception
