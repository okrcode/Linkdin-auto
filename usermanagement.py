import csv
import datetime
from datetime import timedelta

import pytz
import stripe
from authentication import authenticate_user, create_access_token, get_current_user

from automation_functions import (
    ConnectionRequest,
    ConnectionSync,
    FollowRequest,
    FollowSync,
    process_csv_and_queue_requests,
)
from bson import ObjectId
from constants import ERROR_MESSAGES, ERROR_MESSAGES_LINKEDIN, RESPONSE_MESSAGES
from database import (
    get_contacts_collection,
    get_db,
    get_otp_collection,
    get_user_collection,
    get_user_profilecollection,
)
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from functions import generate_otp, get_user_profile
from passlib.context import CryptContext
from pymongo.collection import Collection

from models import (
    InitiateUserLoginModel,
    LinkedInMetrics,
    LinkedInProfileModel,
    LinkedInRegisterModel,
    LoginUsingOTPModel,
    Plan,
    PreferenceModel,
    ResponseBaseModel,
    SubscriptionModel,
    TargetProfileRequest,
    Token,
    TwoFactorValidation,
    UserRegisterModel,
)

# config = Config('.env')
# STRIPE_API_KEY = config.get('STRIPE_API_KEY')

app = FastAPI()

stripe.api_key= "API_key"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password):
    return pwd_context.hash(password)


@app.post(
    "/register",
    response_model=ResponseBaseModel,
    description="The API is to Register a New User",
)
def registeruser(body: UserRegisterModel):
    user = get_user_collection()

    if user.find_one({"email": body.email}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES["EMAIL_ALREADY_REGISTERED"],
        )
    hashed_password = get_password_hash(body.password)
    full_name = f"{body.first_name} {body.last_name}"
    createdat = str(datetime.datetime.now())
    lastupdatedat = str(datetime.datetime.now())

    try:
        customer = stripe.Customer.create(
            email=body.email,
            name=full_name,
        )
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Stripe error: {str(e)}"
        )

    new_user = UserRegisterModel(
        stripe_id=customer.id,
        first_name=body.first_name,
        last_name=body.last_name,
        full_name=full_name,
        email=body.email,
        OTP=body.OTP,
        password=hashed_password,
        email_verified=False,
        created_date=createdat,
        lastupdated_date=lastupdatedat,
        preference=PreferenceModel(
            twofa_validation=TwoFactorValidation(method="email")
        ),
        currentPlan=Plan(
            planId=None, seats=0, subscription_id=None, is_subscribed=False
        ),
    )
    result = user.insert_one(new_user.dict())
    inserted_id = str(result.inserted_id)
    print(inserted_id)
    return ResponseBaseModel(data=None, message=ERROR_MESSAGES["REGISTRATION_SUCCESS"])


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    response = ResponseBaseModel(data=RESPONSE_MESSAGES["data"], message=exc.detail)
    return JSONResponse(status_code=exc.status_code, content=response.dict())


# --Initiate Login API endpoint------
@app.post(
    "/api/v1/initiate-login",
    response_model=ResponseBaseModel,
    description="The API is to Initiate Login by sending OTP to the registered EmailID",
)
def initiate_login(login: InitiateUserLoginModel):

    otp_collection = get_otp_collection()

    user = authenticate_user(login.email, login.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    otp_collection.delete_one({"email": login.email})

    otp = generate_otp()
    ist = pytz.timezone("Asia/Kolkata")
    current_time = datetime.datetime.now(ist)
    valid_till = current_time + timedelta(minutes=5)
    valid_till_naive = valid_till.replace(tzinfo=None)
    valid_till_str = valid_till_naive.isoformat()

    # Store OTP in the database
    otp_document = {
        "user_id": str(user["_id"]),
        "OTP": otp,
        "method": "email",
        "valid_till": valid_till_str,
        "email": login.email,
    }
    otp_collection.insert_one(otp_document)

    return ResponseBaseModel(
        data={"method": "email", "email_id": login.email},
        message="OTP has been sent to the registered method",
    )


# -----login using OTP

@app.post(
    "/api/v1/login",
    response_model=ResponseBaseModel,
    description="The API is to Login User using OTP",
)
def login(login: LoginUsingOTPModel):
    ist = pytz.timezone("Asia/Kolkata")
    otp_collection = get_otp_collection()
    user_collection = get_user_collection()

    otp_document = otp_collection.find_one({"email": login.email})
    user = user_collection.find_one({"email": login.email})

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not otp_document or otp_document["OTP"] != login.OTP:
        raise HTTPException(status_code=401, detail="Invalid OTP")

    # Convert `valid_till` from string to datetime object for comparison
    valid_till = datetime.datetime.fromisoformat(otp_document["valid_till"])
    valid_till = ist.localize(valid_till)
    # Get the current time in UTC to compare with `valid_till`
    current_time = datetime.datetime.now(ist)

    if current_time > valid_till:
        raise HTTPException(status_code=401, detail="Invalid or expired OTP")

    token = create_access_token(user_id=str(user["_id"]), email=str(user["email"]))
    profile = get_user_profile(user["_id"])

    return ResponseBaseModel(
        data={
            "access_token": token,
            "profile": {
                "avatar": profile.get("avatar", ""),
                "full_name": profile.get(
                    "full_name", f"{user['first_name']} {user.get('last_name', '')}"
                ),
            },
        },
        message="Login is successful",
    )


# -----API to create Free-Trial Subscription


@app.post(
    "/create-trial-subscription",
    description="This API creates a free trial subscription for the selected plan.",
)
async def create_trial_subscription(
    body: SubscriptionModel, token: Token = Depends(get_current_user)
):
    user_collection = get_user_collection()
    email = token.email
    # Fetch the user from the database using their email
    user = user_collection.find_one({"email": email})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Retrieve the Stripe customer ID from the user's data
    customer_id = user.get("stripe_id")
    if not customer_id:
        raise HTTPException(
            status_code=400, detail="Customer ID not found for this user"
        )

    try:
        # Create a subscription with a 15-day free trial, without requiring a payment method
        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[
                {
                    "price": body.planId,  # Price ID for the plan
                }
            ],
            trial_period_days=15,  # Set a free trial for 15 days
            payment_behavior="default_incomplete",  # Don't charge the user until payment info is added
        )

        # Update the user's current plan in the database
        user_collection.update_one(
            {"email": email},
            {
                "$set": {
                    "currentPlan.planId": body.planId,
                    "currentPlan.subscription_id": subscription.id,
                    # "currentPlan.is_subscribed": True,
                    "currentPlan.trial_end": subscription.trial_end,
                    "currentPlan.is_trial_active": True,
                }
            },
        )

        return {
            "message": "Trial subscription created successfully",
            "subscription_id": subscription.id,
        }

    except stripe.error.StripeError as e:
        # Handle any errors from Stripe
        raise HTTPException(status_code=400, detail=str(e))


# ---API to create Paid Subscription to the Plan


@app.post(
    "/create-checkout-session",
    description="This API creates a checkout session for the selected plan.",
)
async def create_checkout_session(
    body: SubscriptionModel, token: Token = Depends(get_current_user)
):
    user_collection = get_user_collection()

    email = token.email

    user = user_collection.find_one({"email": email})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    customer_id = user.get("stripe_id")

    if not customer_id:
        raise HTTPException(
            status_code=400, detail="Customer ID not found for this user"
        )

    try:
        # Create a checkout session for the selected plan
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[
                {
                    "price": body.planId,  # Price ID for the plan
                    "quantity": 1,
                },
            ],
            mode="subscription",
            success_url="http://localhost:8000/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="http://localhost:8000/cancel",
        )

        user_collection.update_one(
            {"email": email},
            {
                "$set": {
                    "currentPlan.planId": body.planId,
                    "currentPlan.is_subscribed": True,
                }
            },
        )

        return {"checkout_url": checkout_session.url}

    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---Register Linkedin Profile


@app.post(
    "/register/linkedin",
    response_model=ResponseBaseModel,
    description="The API is to Register a LinkedIn Profile",
)
def register_linkedin_profile(body: LinkedInRegisterModel):

    user_collection = get_user_collection()
    user = user_collection.find_one({"email": body.email})

    # Check if the user exists
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    profile_collection = get_user_profilecollection()
    if profile_collection.find_one({"email": body.email}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES["EMAIL_ALREADY_REGISTERED"],
        )

    if not user.get("currentPlan", {}).get("planId"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES_LINKEDIN["EMAIL_NEEDTO_SUBSCRIBE"],
        )

    linkedin_profile = LinkedInProfileModel(
        profile_id=str(ObjectId()),
        name="",
        username=body.email,
        password=body.password,
        requires_2fa=False,
        profile_link="",
        profile_title="",
        metrics=LinkedInMetrics(connections=0, followers=0, following=0),
        seat_activated=False,
    )
    # here we are Assigning a unique profile_id
    linkedin_profile.profile_id = str(ObjectId())

    # Save LinkedIn profile under the user's email
    profile_collection.update_one(
        {"email": body.email},
        {"$set": {"linkedin_profile": linkedin_profile.dict()}},
        upsert=True,
    )

    return ResponseBaseModel(
        data=None, message="LinkedIn profile registered successfully."
    )


# ------fetch connections, followers and following count  and store it in database collection

@app.post("/fetch-linkedin-metrics/")
def fetch_linkedin_metrics(body: LinkedInRegisterModel):
    profile_collection = get_user_profilecollection()

    # Retrieve LinkedIn profile from the database
    user_profile = profile_collection.find_one({"email": body.email})

    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LinkedIn profile not found for the given email.",
        )

    linkedin_profile = user_profile.get("linkedin_profile", {})
    if not linkedin_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LinkedIn profile data is missing for the given email.",
        )

    username = linkedin_profile.get("username")
    password = linkedin_profile.get("password")

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LinkedIn username or password is missing.",
        )
    sync = ConnectionSync()
    # Log in to LinkedIn and fetch metrics using Selenium
    # sync.login(username,password,cookies_location='cookies')
    connection_collection = get_contacts_collection()

    try:
        contacts = sync.download(username, password)
        connection_collection.insert_many(contacts)
        connections_count = len(contacts)

        following = sync.get_following()
        following_count = len(following)

        followers = sync.get_follower()
        follower_count = len(followers)

        # Update the connections count in the LinkedIn profile
        profile_collection.update_one(
            {"email": body.email},
            {
                "$set": {
                    "linkedin_profile.metrics.connections": connections_count,
                    "linkedin_profile.metrics.following": following_count,
                    "linkedin_profile.metrics.followers": follower_count,
                }
            },
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "success", "message": "Metrics fetched and updated successfully."}


# ------To Like, message target person by passing their name


@app.get("/like-target-people-post")
def get_target_user_from_db(
    target_name: str, token: Token = Depends(get_current_user)
) -> dict:
    connections_collection = get_contacts_collection()
    target_user = connections_collection.find_one({"name": target_name})
    email = token.email
    if target_user:
        print(f"Found target user: {target_user['name']}")
        profile_link = target_user.get(
            "profile_link"
        )  # Access profile_link from target_user
        # return {"profile_link": profile_link}
    else:
        raise HTTPException(
            status_code=404, detail=f"No user found with name: {target_name}"
        )

    profile_collection = get_user_profilecollection()

    # Retrieve LinkedIn profile from the database
    user_profile = profile_collection.find_one({"email": email})
    print(profile_link)

    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LinkedIn profile not found for the given email.",
        )

    linkedin_profile = user_profile.get("linkedin_profile", {})
    if not linkedin_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LinkedIn profile data is missing for the given email.",
        )

    username = linkedin_profile.get("username")
    password = linkedin_profile.get("password")

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LinkedIn username or password is missing.",
        )

    sync1 = ConnectionSync()
    # sync=ConnectionRequest(profile_link)

    # sync=ConnectionSync()
    try:
        # ----without adding celery

        sync1.login(username, password, cookies_location="cookies")
        sync1.like_all_posts(profile_link)

        message = "Hey how are you"
        sync1.send_message(profile_link, message)
        print("message sent")

        sync1.extract_info(profile_link)
        profile_info = sync1.extract_info(profile_link)
        print(profile_info)

        # Optional: Update the profile information in MongoDB
        connections_collection.update_one(
            {"profile_link": profile_link},
            {
                "$set": {"headline": profile_info.get("headline")}
            },  # Save the extracted info into the collection
            upsert=True,  # If not found, create a new document
        )


        #---adding celery

        # sync.login(username,password,cookies_location='cookies')
        # #login_to_linkedin_task.apply_async(args=[username,password],kwargs={'cookies_location': 'cookies'})
        # print(profile_link)
        
        # message_text="Hey how are you?"
        # send_messages_task=send_message_task.apply_async(args=[profile_link, message_text],countdown=60)

        # like_posts_task=like_post_task.apply_async(args=[profile_link],countdown=60)
        # print("hii")
        # connections_collection.update_one({"profileId": profile_link}, {"$set": {"status": "Session Active"}})

        # return {"message": "Liking posts and sending message are scheduled in the background.", "task_id1": like_posts_task.id,"task_id2":send_messages_task.id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

#-------Check the status of the celery task

# @app.get("/task-status/{task_id}")
# def get_task_status(task_id:str):
#     result = AsyncResult(task_id, app=celery_app)
#     if result.ready():
#         return {"status": result.status, "result": result.result}
#     else:
#         return {"status": result.status, "message": "Task not completed yet."}







@app.post("/follow-profile")
async def follow_profile(
    request: TargetProfileRequest, token: Token = Depends(get_current_user)
):
    profiles_collection = get_user_profilecollection()
    contacts_collection = (
        get_contacts_collection()
    )  # Assuming there's a collection for contacts
    # sync = None  # Initialize sync variable

    try:
        # Fetch the profile from the contact database using the provided name
        contact = contacts_collection.find_one(
            {"name": request.name}
        )  # Modify to use name from request

        if not contact or "profile_link" not in contact:
            raise HTTPException(
                status_code=404, detail="Profile URL not found for the provided name"
            )

        profile_url = contact["profile_link"]  # Extract the profile URL

        # Fetch LinkedIn credentials from the database
        profile = profiles_collection.find_one(
            {"linkedin_profile.username": {"$exists": True}}
        )
        if not profile:
            raise HTTPException(
                status_code=404, detail="Profile credentials not found in the database"
            )

        email = profile.get("linkedin_profile", {}).get("username")
        password = profile.get("linkedin_profile", {}).get("password")

        if not email or not password:
            raise HTTPException(
                status_code=400, detail="Email or password not found in the database"
            )

        sync = FollowSync(email=email, password=password)

        # Login to LinkedIn
        sync.login_linkedin(email, password)

        # Use the send function with the fetched profile URL
        sync.send(profile_url)

        return {
            "success": True,
            "message": "Profile interaction completed successfully",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if sync:
            sync.close()


@app.post("/connections/upload-contacts/")
async def upload_contacts(
    file: UploadFile = File(...),
    db: Collection = Depends(get_db),
    token: Token = Depends(get_current_user),
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")

    contents = await file.read()
    csv_data = contents.decode("utf-8").splitlines()
    csv_reader = csv.reader(csv_data)

    contacts = []
    for row in csv_reader:
        if len(row) < 1:
            continue
        item = {"profile_link": row[0]}
        contacts.append(item)

    if contacts:
        db["connection"].delete_many({})
        db["connection"].insert_many(contacts)  # Insert all contacts at once

    return {"message": "CSV file uploaded and data stored in MongoDB"}


@app.post("/connections/send-follow-requests/")
async def send_follow_requests(
    db: Collection = Depends(get_db), token: Token = Depends(get_current_user)
):
    profile_collection = db["connection"]
    profiles = profile_collection.find()

    # Retrieve LinkedIn credentials from MongoDB or environment variables
    profile = db["profiles"].find_one({"linkedin_profile.username": {"$exists": True}})
    if not profile:
        raise HTTPException(
            status_code=404, detail="Profile credentials not found in the database"
        )

    email = profile.get("linkedin_profile", {}).get("username")
    password = profile.get("linkedin_profile", {}).get("password")

    if not email or not password:
        raise HTTPException(status_code=400, detail="Incorrect Email or password ")

    # Initialize FollowRequest class
    sync = FollowRequest(email=email, password=password)

    try:
        sync.login_linkedin(email, password)  # Login to LinkedIn

        for profile in profiles:
            profile_url = profile.get("profile_link")
            if profile_url:
                try:
                    # Send follow request for each profile
                    sync.send(profile_url)
                    print(f"Follow request sent to: {profile_url}")
                except Exception as e:
                    print(
                        f"Failed to send follow request to: {profile_url}. Error: {str(e)}"
                    )
    finally:
        sync.close()  # Close the browser after all requests are sent

    return {"message": "Follow requests sent to all profile links."}


@app.post("/connections/send-connection-request")
async def send_connection_request(
    db: Collection = Depends(get_db), token: Token = Depends(get_current_user)
):
    profile_collection = db["connection"]
    profiles = profile_collection.find()

    profile = db["profiles"].find_one({"linkedin_profile.username": {"$exists": True}})
    if not profile:
        raise HTTPException(
            status_code=404, detail="Profile credentials not found in the database"
        )

    email = profile.get("linkedin_profile", {}).get("username")
    password = profile.get("linkedin_profile", {}).get("password")

    if not email or not password:
        raise HTTPException(status_code=404, detail="Invalid email or password")
    sync = ConnectionRequest(email=email, password=password)

    try:
        sync.login_linkedin(email, password)
        for profile in profiles:
            profile_url = profile.get("profile_link")
            if profile_url:
                try:
                    sync.send(profile_url)
                    print(f"connection request has been sent to:{profile_url}")

                except Exception as e:
                    print(f"failed to send connection request to:{profile_url}.Error:{str(e)}")

    finally:
        sync.close()

    return {"meassage": "Connection request has been sent to all the profiles"}






@app.post("/upload-csv/")
async def upload_csv(file: UploadFile = File(...)):

    if file.content_type != "text/csv":
        raise HTTPException(
            status_code=400, detail="Invalid file format. Please upload a CSV file."
        )
    await process_csv_and_queue_requests(file)
    return {
        "message": "File uploaded and connection requests are queued for processing."
    }

