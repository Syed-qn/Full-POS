from pydantic import BaseModel


class OrgSignupIn(BaseModel):
    name: str
    owner_email: str
    password: str


class OrgLoginIn(BaseModel):
    owner_email: str
    password: str


class BranchIn(BaseModel):
    name: str
    lat: float
    lng: float
