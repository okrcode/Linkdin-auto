import random
import string

from database import get_user_collection


def generate_otp(length=6):
    """Generate a random OTP of given length."""
    return "".join(random.choices(string.digits, k=length))


def get_user_profile(user_id: str):
    user_collection = get_user_collection()
    user = user_collection.find_one({"_id": user_id})
    if not user:
        return {}

    # Assume the profile is stored in a separate collection
    profile = user_collection.find_one({"user_id": user_id})

    if not profile:
        # If no profile is found, return the user's name from the user collection
        return {
            "avatar": "",
            "full_name": f"{user['first_name']} {user.get('last_name', '')}",
        }

    # If profile exists, return the avatar and full name
    return {
        "avatar": profile.get("avatar", ""),
        "full_name": profile.get(
            "full_name", f"{user['first_name']} {user.get('last_name', '')}"
        ),
    }
