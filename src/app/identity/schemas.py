from pydantic import BaseModel, ConfigDict, Field


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=7, max_length=32)
    password: str = Field(min_length=8)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class LoginIn(BaseModel):
    phone: str = Field(min_length=7, max_length=32)
    password: str = Field(min_length=1)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    lat: float
    lng: float
    settings: dict
