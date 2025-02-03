from typing import Any, Optional

from pydantic import BaseModel, Field


class ResponseBaseModel(BaseModel):
    data: Any
    message: str


class UserRegisterModel(BaseModel):
    first_name: str
    last_name: str
    email: str = Field(
        "ABCD@XYZ", description="The email of the user", example="Widget"
    )
    password: str
    OTP: bool

    class Config:
        extra = "allow"


class LinkedInRegisterModel(BaseModel):
    email: str = Field(
        "ABCD@XYZ", description="The email of the user", example="Widget"
    )
    password: str


class Plan(BaseModel):
    planId: Optional[str] = None
    subscription_id: Optional[str] = None
    is_subscribed: bool
    seats: int = 0


class TwoFactorValidation(BaseModel):
    method: str = "email"


class PreferenceModel(BaseModel):
    twofa_validation: TwoFactorValidation


class InitiateUserLoginModel(BaseModel):
    email: str = Field(
        "ABCD@XYZ", description="The email of the user", example="Widget"
    )
    password: str


class LoginUsingOTPModel(BaseModel):
    email: str = Field(
        "ABCD@XYZ", description="The email of the user", example="Widget"
    )
    OTP: str


class LinkedInMetrics(BaseModel):
    connections: int = Field(0)
    followers: int = Field(0)
    following: int = Field(0)


class LinkedInProfileModel(BaseModel):
    profile_id: str = Field("")
    name: str = Field("")
    username: str = Field("")
    password: str = Field("")
    requires_2fa: bool = Field(False)
    profile_link: str = Field("")
    profile_title: str = Field("")
    metrics: LinkedInMetrics = Field(default_factory=LinkedInMetrics)
    seat_activated: bool = Field(False)


class SubscriptionModel(BaseModel):
    planId: str


class TrialSubscriptionModel(BaseModel):
    price_id: str
    trial_days: int = 15


class OTPCollectionModel(BaseModel):
    user_id: str
    OTP: int
    method: str
    valid_till_str: int


class Token(BaseModel):
    access_token: str
    token_type: str
    email: str = Field(
        "ABCD@XYZ", description="The email of the user", example="Widget"
    )


class TargetProfileRequest(BaseModel):
    name: str
