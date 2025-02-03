from pymongo import MongoClient
from pymongo.collection import Collection

MONGODB_URL = "mongodb://localhost:27017/"
DATABASE_NAME = "mydatabase"


client = MongoClient(MONGODB_URL)
db = client[DATABASE_NAME]

users_collection: Collection = db["users"]
profiles_collection: Collection = db["profiles"]
contacts_collection: Collection = db["contacts"]
contacts_collection: Collection = db["plans"]


def get_db():
    return db


def get_user_collection() -> Collection:
    return db["users"]


def get_user_profilecollection() -> Collection:
    return db["profiles"]


def get_otp_collection() -> Collection:
    return db["OTP"]


# def get_stripePlan_collection() -> Collection:
#     return db["plan"]


def get_contacts_collection() -> Collection:
    return db["contacts"]
