import asyncio
import csv
import os
import pickle
import time
from enum import Enum
from io import StringIO
from typing import Dict, List

import requests
from bs4 import BeautifulSoup
from fastapi import UploadFile
from selenium import webdriver
from selenium.common.exceptions import (
    ElementNotInteractableException,
    NoSuchElementException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

profile_queue = []


class ProfileState(str, Enum):
    CONNECTED = "connected"
    PENDING = "pending"
    NOT_CONNECTED = "not_connected"


class ConnectionCommon:

    def __init__(self, driver, profile_url):
        self.driver = driver
        self.profile_url = profile_url

    def click_more_action(self):
        button = self.driver.find_element(
            By.XPATH,
            '//div[contains(@class, "pvs-sticky-header-profile-actions")]/div//button[@aria-label="More actions" and .//span[text()="More"]]',
        )
        button.click()
        time.sleep(3)

    def slide_down(self, until=None, wait=5):
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        print("Document is ready")
        if until:
            pass
        else:
            time.sleep(wait)

    def minimize_messaging_if_available(self):
        try:
            svg_element = self.driver.find_element(
                By.CSS_SELECTOR, 'svg[data-test-icon="chevron-down-small"]'
            )
            parent_button = svg_element.find_element(By.XPATH, "./ancestor::button")
            parent_button.click()
        except NoSuchElementException:
            print("Hello")
            pass

    def _check_if_request_already_send_or_pending(self):
        try:
            xpath_locator = "//button[contains(@aria-label, 'Pending, click to withdraw invitation sent to') and contains(@class, 'pvs-sticky-header-profile-actions__action') and @type='button']"
            self.driver.find_element(By.XPATH, xpath_locator)
            return True
        except NoSuchElementException:
            return False

    def get_status(self):
        if "Remove Connection" in self.driver.page_source:
            return ProfileState.CONNECTED
        if self._check_if_request_already_send_or_pending():
            return ProfileState.PENDING
        return ProfileState.NOT_CONNECTED

    def login_linkedin(self, email, password):
        self.driver.get("https://www.linkedin.com/login")
        time.sleep(2)

        # Enter the username
        username_field = self.driver.find_element(By.ID, "username")
        username_field.send_keys(email)

        # Enter the password
        password_field = self.driver.find_element(By.ID, "password")
        password_field.send_keys(password)

        # Submit the form
        password_field.send_keys(Keys.RETURN)
        time.sleep(5)


class ConnectionSync:
    def __init__(self, message=None):
        chrome_options = Options()
        # Uncomment for headless mode
        # chrome_options.add_argument("--headless")
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=chrome_options
        )
        self.message = message

    def login_linkedin(self, email, password):
        self.driver.get("https://www.linkedin.com/login")
        time.sleep(2)

        # Enter the username
        username_field = self.driver.find_element(By.ID, "username")
        username_field.send_keys(email)

        # Enter the password
        password_field = self.driver.find_element(By.ID, "password")
        password_field.send_keys(password)

        # Submit the form
        password_field.send_keys(Keys.RETURN)
        time.sleep(5)

    def login(self, email, password, cookies_location):
        # Create cookies directory if it doesn't exist
        if not os.path.exists(cookies_location):
            os.makedirs(cookies_location, exist_ok=True)

        # Path to save and load cookies
        cookies_file_path = f"{cookies_location}/{email}_linkedin_cookies.pkl"

        # Load cookies if available
        if os.path.exists(cookies_file_path):
            self.driver.get("https://www.linkedin.com")
            with open(cookies_file_path, "rb") as cookies_file:
                cookies = pickle.load(cookies_file)
                for cookie in cookies:
                    self.driver.add_cookie(cookie)
            self.driver.refresh()

        # Check if already logged in by loading the LinkedIn feed page
        self.driver.get("https://www.linkedin.com/feed")
        time.sleep(5)

        # If not logged in, perform login
        if (
            "session_redirect" in self.driver.current_url
            or "uas/login?session_redirect" in self.driver.current_url
        ):
            try:
                username_field = self.driver.find_element(By.ID, "username")
                username_field.send_keys(email)
            except Exception:
                pass  # Username field might not be found due to page structure changes

            password_field = self.driver.find_element(By.ID, "password")
            password_field.send_keys(password)

            # Submit the form
            password_field.send_keys(Keys.RETURN)

            # Wait for login to complete and check for 2FA flow
            time.sleep(20)

            # Save cookies for future use
            cookies = self.driver.get_cookies()
            with open(cookies_file_path, "wb") as cookies_file:
                pickle.dump(cookies, cookies_file)

            if "feed" in self.driver.current_url:
                print("Login successful!")
                return True, "Login Success"
            else:
                print("Login failed.")
                return False, "Login Failed"
        else:
            print("Already logged in using saved cookies.")
            return True, "Login Success, Already Logged in"

    def _extract_li_from_div(
        self, html_content: str, target_class: str, function
    ) -> List[Dict[str, str]]:
        soup = BeautifulSoup(html_content, "html.parser")
        divs = soup.find_all("div", class_=target_class)
        li_elements = []
        for div in divs:
            li_elements.extend(div.find_all("li"))
        contacts = []
        for li_element in li_elements:
            contacts.append(function(li_element))
        return contacts

    def _extract_connection_info(self, li_element) -> Dict[str, str]:
        name = li_element.find("span", class_="mn-connection-card__name").get_text(
            strip=True
        )
        profile_link = li_element.find("a", class_="mn-connection-card__link")["href"]
        full_profile_link = f"https://www.linkedin.com{profile_link}"
        return {"name": name, "profile_link": full_profile_link}

    def download(self, username: str, password: str) -> List[Dict[str, str]]:
        # Call the login function with the same driver
        self.login_linkedin(username, password)
        self.driver.get(
            "https://www.linkedin.com/mynetwork/invite-connect/connections/"
        )
        time.sleep(5)
        self.minimize_messaging_if_available()

        all_contacts = []
        seen_profiles = set()  # Keep track of seen profile links
        last_height = 0
        new_height = self.driver.execute_script("return document.body.scrollHeight")

        while last_height != new_height:
            last_height = new_height
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(5)  # Adjust this time if necessary

            new_contacts = self._extract_li_from_div(
                self.driver.page_source,
                target_class="scaffold-finite-scroll__content",
                function=self._extract_connection_info,
            )

            # Only add unique contacts
            for contact in new_contacts:
                if contact["profile_link"] not in seen_profiles:
                    all_contacts.append(contact)
                    seen_profiles.add(contact["profile_link"])

            new_height = self.driver.execute_script("return document.body.scrollHeight")

            # Check for "Show more" button and click if available
            try:
                button = self.driver.find_element(
                    By.XPATH,
                    "//button[contains(@class, 'artdeco-button') and .//span[text()='Show more results']]",
                )
                button.click()
                time.sleep(5)  # Wait for more results to load
            except Exception as e:
                print(f"No more 'Show more results' button or error: {e}")

        print(f"Found {len(all_contacts)} unique connections")
        return all_contacts

    def minimize_messaging_if_available(self):
        try:
            messaging_element = self.driver.find_element(
                By.CSS_SELECTOR, ".msg-overlay-bubble-header"
            )
            if messaging_element.is_displayed():
                self.driver.execute_script(
                    "arguments[0].style.display = 'none';", messaging_element
                )
        except Exception as e:
            print(f"Messaging element not found or not displayed: {e}")

    def _extract_following_info(self, li_element):
        # Extract name
        name = li_element.find("span", class_="entity-result__title-text").get_text(
            strip=True
        )
        occupation = li_element.find(
            "div", class_="entity-result__primary-subtitle"
        ).get_text(strip=True)
        # TODO: The link is not directly mapping to the actual url, probably we require another service to
        # normalize it. Like a seperate instance later to make the linkage correct. Else we can expect duplicate records
        profile_link = li_element.find("a", class_="app-aware-link")["href"]
        filename = profile_link.strip("/").replace("/", "_") + ".jpg"

        # Create data folder if it doesn't exist
        if not os.path.exists("data"):
            os.makedirs("data")

        # Extract image URL\
        image_link = None
        try:
            img_tag = li_element.find("img", class_="presence-entity__image")
            img_url = img_tag["src"]
            # Check if the image is a placeholder or an actual image
            if img_url.startswith("data:image/"):  # Placeholder image
                print(f"Skipping placeholder image for {profile_link}")
            else:
                # Download the image and save it with the profile link as filename
                img_data = requests.get(img_url).content
                with open(os.path.join("data", filename), "wb") as handler:
                    handler.write(img_data)
                    print(
                        f"Image downloaded for {profile_link} and saved as {filename}"
                    )
                image_link = filename
        except Exception:
            pass

        return {
            "name": name,
            "occupation": occupation,
            "profile_link": profile_link,
            "avatar": image_link,
        }

    def get_following(self):
        # self.login_linkedin(username, password)
        self.driver.get(
            "https://www.linkedin.com/mynetwork/network-manager/people-follow/following/"
        )
        page_state = self.driver.execute_script("return document.readyState;")
        while page_state != "complete":
            page_state = self.driver.execute_script("return document.readyState;")
        time.sleep(5)
        self.minimize_messaging_if_available()
        # loader_xpath = "//div[contains(@class, 'artdeco-loader') and .//div[text()='Loading more results']]"
        button_locator = "//button[contains(@class, 'artdeco-button') and .//span[text()='Show more results']]"
        time.sleep(5)
        while "Show more results" in self.driver.page_source:
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            try:
                button = self.driver.find_element(By.XPATH, button_locator)
                if button:
                    button.click()
            except Exception:
                pass
            time.sleep(5)
        contacts = self._extract_li_from_div(
            self.driver.page_source,
            target_class="scaffold-finite-scroll__content",
            function=self._extract_following_info,
        )
        print(f"Found {len(contacts)}")
        return contacts

    def _extract_follower_info(self, li_element):
        # Extract name
        name_ele = li_element.find("span", class_="entity-result__title-text")
        occupation_ele = li_element.find(
            "div", class_="entity-result__primary-subtitle"
        )
        try:
            name = name_ele.get_text(strip=True) if name_ele else "Name not found"
        except Exception as e:
            print(f"Error getting name: {e}")
            name = "Name not found"

        try:
            occupation = (
                occupation_ele.get_text(strip=True)
                if occupation_ele
                else "Occupation not found"
            )
        except Exception as e:
            print(f"Error getting occupation: {e}")
            occupation = "Occupation not found"

        return {
            "name": name,
            "occupation": occupation,
            # 'profile_link': profile_link,
            # "avatar": image_link
        }

    def get_follower(self):
        # self.login_linkedin(username, password)
        print("here it came")
        self.driver.get(
            "https://www.linkedin.com/mynetwork/network-manager/people-follow/followers/"
        )
        print("hi")
        page_state = self.driver.execute_script("return document.readyState;")
        while page_state != "complete":
            page_state = self.driver.execute_script("return document.readyState;")
        time.sleep(5)
        self.minimize_messaging_if_available()
        # loader_xpath = "//div[contains(@class, 'artdeco-loader') and .//div[text()='Loading more results']]"
        button_locator = "//button[contains(@class, 'artdeco-button') and .//span[text()='Show more results']]"
        time.sleep(5)
        while "Show more results" in self.driver.page_source:
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            try:
                button = self.driver.find_element(By.XPATH, button_locator)
                if button:
                    button.click()
            except Exception:
                pass
            time.sleep(5)
        contacts = self._extract_li_from_div(
            self.driver.page_source,
            target_class="scaffold-finite-scroll__content",
            function=self._extract_follower_info,
        )
        # print(contacts)
        # print("here it came 3")
        print(f"Found {len(contacts)}")
        return contacts

    def slide_down(self, until=None, wait=8):

        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        print("Page scrolled down")
        if until:
            pass
        else:
            time.sleep(wait)  # Wait for posts to load before proceeding

    def like_all_posts(self, profile_link):
        # Navigate to the user's profile
        self.driver.get(profile_link)
        time.sleep(5)
        self.driver.get(f"{profile_link}/recent-activity/all/")
        while True:
            try:
                # Locate the Like button for unliked posts
                like_button = WebDriverWait(self.driver, 10).until(
                    ec.element_to_be_clickable(
                        (
                            By.XPATH,
                            '//button[@aria-label="React Like" and @aria-pressed="false"]',
                        )
                    )
                )
                like_button.click()  # Click the Like button
                print("Post liked successfully!")
                time.sleep(2)  # Delay to avoid spamming actions

            except Exception as e:
                print(f"No more likeable posts found or an error occurred: {e}")
                # Scroll down to load more posts and retry
                self.slide_down(self.driver)
                time.sleep(7)
                return  # Allow time for new posts to load

    def send_message(self, profile_link, message_text):
        # print("hi")
        self.driver.get(profile_link)
        time.sleep(5)

        try:
            # Locate the 'Message' button
            message_button = WebDriverWait(self.driver, 10).until(
                ec.element_to_be_clickable(
                    (
                        By.XPATH,
                        '//button[contains(@class, "artdeco-button artdeco-button--2 artdeco-button--primary ember-view pvs-profile-actions__action")]',
                    )
                )
            )
            message_button.click()
            time.sleep(2)

            # Locate the message input area and type the message
            message_area = WebDriverWait(self.driver, 10).until(
                ec.presence_of_element_located(
                    (By.XPATH, '//div[contains(@role, "textbox")]')
                )
            )
            message_area.send_keys(message_text)
            time.sleep(3)

            # Send the message
            send_button = WebDriverWait(self.driver, 10).until(
                ec.element_to_be_clickable(
                    (
                        By.XPATH,
                        '//button[contains(@class, "msg-form__send-button artdeco-button artdeco-button--1")]',
                    )
                )
            )
            send_button.click()
            print("Message sent successfully!")

        except Exception:
            print("Message button not found or unable to send message.")

    def extract_info(self, profile_link):
        self.driver.get(profile_link)
        time.sleep(5)
        self.minimize_messaging_if_available()

        profile_data = {}

        # Extract the user's name
        # try:
        #     profile_data['name'] = self.driver.find_element(By.CSS_SELECTOR, ".text-heading-xlarge").text.strip()
        # except:
        #     profile_data['name'] = None

        # Extract the user's current job title and company
        try:
            profile_data["headline"] = self.driver.find_element(
                By.CSS_SELECTOR, ".text-body-medium.break-words"
            ).text.strip()
        except Exception:
            profile_data["headline"] = None

        # Extract the user's current company
        # try:
        #     company_element = self.driver.find_element(By.XPATH, '//span[contains(@class, "lniOYEbXEnudKkpVpbiohPfWcAiqqXhnFiCCns") and contains(@class, "text-body-small t-black")]')
        #     profile_data['company_name'] = company_element.text.strip()
        # except:
        #     profile_data['current_company'] = None
        # #print(profile_data)
        return profile_data


class FollowSync(ConnectionSync):
    def __init__(self, email: str, password: str):
        chrome_options = Options()
        # Uncomment for headless mode
        # chrome_options.add_argument("--headless")
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=chrome_options
        )
        self.email = email
        self.password = password

    def click_more_action(self):
        button = self.driver.find_element(
            By.XPATH,
            '//div[contains(@class, "pvs-sticky-header-profile-actions")]/div//button[@aria-label="More actions" and .//span[text()="More"]]',
        )
        button.click()
        time.sleep(3)

    def get_status(self):
        if "Remove Connection" in self.driver.page_source:
            return ProfileState.CONNECTED
        if self._check_if_request_already_send_or_pending():
            return ProfileState.PENDING
        return ProfileState.NOT_CONNECTED

    def _follow_from_drop_down(self):
        self.click_more_action()
        xpath_locator = '//div[contains(@class, "artdeco-dropdown__item") and .//span[text()="Follow"]]'
        buttons = self.driver.find_elements(By.XPATH, xpath_locator)
        for button in buttons:
            try:
                button.click()
                return True
            except ElementNotInteractableException:
                pass
        return False

    def _follow_from_button(self):
        try:
            xpath_locator = '//button[contains(@aria-label, "Follow") and contains(@class, "pvs-sticky-header-profile-actions__action") and @type="button"]'
            button = self.driver.find_element(By.XPATH, xpath_locator)
            button.click()
            return True
        except NoSuchElementException:
            return False

    def get_and_follow_company_profiles(self, linkedin_experience_url):
        self.driver.get(linkedin_experience_url)
        time.sleep(5)  # Wait for the page to load

        # Find company profile links
        company_elements = self.driver.find_elements(
            By.CSS_SELECTOR, 'a[href*="/company/"]'
        )
        company_profiles = [elem.get_attribute("href") for elem in company_elements]

        # Follow each company profile
        for profile_url in company_profiles:
            self.driver.get(profile_url)
            time.sleep(5)  # Wait for the page to load

            try:
                # Find and click the "Follow" button
                follow_button = self.driver.find_element(
                    By.XPATH,
                    '//button[contains(@aria-label, "Follow") and @type="button"]',
                )
                if follow_button.text.lower() == "follow":
                    follow_button.click()
                    print(f"Followed {profile_url}")
                else:
                    print(f"Already following {profile_url}")
            except NoSuchElementException as e:
                print(f"Could not follow {profile_url}: {e}")

            time.sleep(5)

    def send(self, profile_url: str):
        self.profile_url = profile_url
        self.driver.get(profile_url)
        time.sleep(5)
        print("Waiting for document to be ready")
        page_state = self.driver.execute_script("return document.readyState;")
        while page_state != "complete":
            page_state = self.driver.execute_script("return document.readyState;")
        self.slide_down()
        print("Document is ready")
        time.sleep(5)
        self.minimize_messaging_if_available()

        connection_status = self.get_status()
        if connection_status in [ProfileState.PENDING]:
            return connection_status

        direct_follow_available = self._follow_from_button()
        if not direct_follow_available:
            self._follow_from_drop_down()
            time.sleep(5)

        # Get the URL for the experience section and follow the companies
        experience_url = f"{self.profile_url}/details/experience"
        self.get_and_follow_company_profiles(experience_url)

        return True

    def close(self):
        self.driver.quit()


class FollowRequest(ConnectionCommon):

    def __init__(self, email: str, password: str):
        chrome_options = Options()
        # Uncomment for headless mode
        # chrome_options.add_argument("--headless")
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=chrome_options
        )
        self.email = email
        self.password = password

    def _follow_from_drop_down(self):
        self.click_more_action()
        xpath_locator = '//div[contains(@class, "artdeco-dropdown__item") and .//span[text()="Follow"]]'
        buttons = self.driver.find_elements(By.XPATH, xpath_locator)
        for button in buttons:
            try:
                button.click()
                return True
            except ElementNotInteractableException:
                pass
        return False

    def _follow_from_button(self):
        try:
            xpath_locator = '//button[contains(@aria-label, "Follow") and contains(@class, "follow   org-company-follow-button org-top-card-primary-actions__action artdeco-button artdeco-button--primary") and @type="button"]'
            button = self.driver.find_element(By.XPATH, xpath_locator)
            button.click()
            return True
        except NoSuchElementException:
            return False

    def send(self, profile_url=None):
        self.profile_url = profile_url
        self.driver.get(self.profile_url)
        time.sleep(5)
        print("Waiting for document to be ready")
        page_state = self.driver.execute_script("return document.readyState;")
        while page_state != "complete":
            page_state = self.driver.execute_script("return document.readyState;")
        self.slide_down()
        print("Document is ready")
        time.sleep(5)
        self.minimize_messaging_if_available()

        connection_status = self.get_status()
        if connection_status in [ProfileState.PENDING]:
            return connection_status

        direct_follow_available = self._follow_from_button()
        if not direct_follow_available:
            self._follow_from_drop_down()
            time.sleep(5)

        return True

    def close(self):
        self.driver.quit()


class ConnectionRequest(ConnectionCommon):

    def __init__(self, email: str, password: str):
        chrome_options = Options()
        # Uncomment for headless mode
        # chrome_options.add_argument("--headless")
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=chrome_options
        )
        self.email = email
        self.password = password

    def _connect_from_drop_down(self):
        self.click_more_action()
        xpath_locator = '//div[contains(@class, "artdeco-dropdown__item") and .//span[text()="Connect"]]'
        buttons = self.driver.find_elements(By.XPATH, xpath_locator)
        for button in buttons:
            try:
                button.click()
            except ElementNotInteractableException:
                pass

    def _connect_from_button(self):
        try:
            xpath_locator = '//button[contains(@aria-label, "connect") and contains(@class, "pvs-sticky-header-profile-actions__action") and @type="button"]'
            button = self.driver.find_element(By.XPATH, xpath_locator)
            button.click()
            return True
        except NoSuchElementException:
            return False

    def send(self, profile_url=None):
        self.profile_url = profile_url
        self.driver.get(self.profile_url)
        time.sleep(5)
        print("Waiting for document to be ready")
        page_state = self.driver.execute_script("return document.readyState;")
        while page_state != "complete":
            page_state = self.driver.execute_script("return document.readyState;")
        self.slide_down()
        print("Document is ready")
        time.sleep(5)
        # Minimize Messaging
        self.minimize_messaging_if_available()

        connection_status = self.get_status()
        if connection_status in [ProfileState.CONNECTED, ProfileState.PENDING]:
            return connection_status
        # Check if Connect is available in header
        direct_connect_available = self._connect_from_button()
        if not direct_connect_available:
            self._connect_from_drop_down()
        time.sleep(2)
        if "Add a note to your invitation" in self.driver.page_source:
            if (
                "To verify this member knows you, please enter their email to connect"
                in self.driver.page_source
            ):
                print("Requires Email to send Request")
                return
            if self.message:
                xpath_locator = "//button[@aria-label='Add a note']"
                button = self.driver.find_element(By.XPATH, xpath_locator)
                button.click()

            else:
                xpath_locator = "//button[@aria-label='Send without a note']"
                button = self.driver.find_element(By.XPATH, xpath_locator)
                button.click()
        return True

    def close(self):
        self.driver.quit()


class SendingConnectionRequest(ConnectionCommon):

    def __init__(self, profile_url, message=None):
        chrome_options = Options()
        # Uncomment for headless mode
        # chrome_options.add_argument("--headless")
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=chrome_options
        )
        self.profile_url = profile_url
        self.message = message

    def _connect_from_drop_down(self):
        self.click_more_action()
        xpath_locator = '//div[contains(@class, "artdeco-dropdown__item") and .//span[text()="Connect"]]'
        buttons = self.driver.find_elements(By.XPATH, xpath_locator)
        for button in buttons:
            try:
                button.click()
            except ElementNotInteractableException:
                pass

    def _connect_from_button(self):
        try:
            xpath_locator = '//button[contains(@aria-label, "connect") and contains(@class, "pvs-sticky-header-profile-actions__action") and @type="button"]'
            button = self.driver.find_element(By.XPATH, xpath_locator)
            button.click()
            return True
        except NoSuchElementException:
            return False

    def login(self, email, password, cookies_location):
        # Create cookies directory if it doesn't exist
        if not os.path.exists(cookies_location):
            os.makedirs(cookies_location, exist_ok=True)

        # Path to save and load cookies
        cookies_file_path = f"{cookies_location}/{email}_linkedin_cookies.pkl"

        # Load cookies if available
        if os.path.exists(cookies_file_path):
            self.driver.get("https://www.linkedin.com")
            with open(cookies_file_path, "rb") as cookies_file:
                cookies = pickle.load(cookies_file)
                for cookie in cookies:
                    self.driver.add_cookie(cookie)
            self.driver.refresh()

        # Check if already logged in by loading the LinkedIn feed page
        self.driver.get("https://www.linkedin.com/feed")
        time.sleep(5)

        # If not logged in, perform login
        if (
            "session_redirect" in self.driver.current_url
            or "uas/login?session_redirect" in self.driver.current_url
        ):
            try:
                username_field = self.driver.find_element(By.ID, "username")
                username_field.send_keys(email)
            except Exception:
                pass  # Username field might not be found due to page structure changes

            password_field = self.driver.find_element(By.ID, "password")
            password_field.send_keys(password)

            # Submit the form
            password_field.send_keys(Keys.RETURN)

            # Wait for login to complete and check for 2FA flow
            time.sleep(20)

            # Save cookies for future use
            cookies = self.driver.get_cookies()
            with open(cookies_file_path, "wb") as cookies_file:
                pickle.dump(cookies, cookies_file)

            if "feed" in self.driver.current_url:
                print("Login successful!")
                return True, "Login Success"
            else:
                print("Login failed.")
                return False, "Login Failed"
        else:
            print("Already logged in using saved cookies.")
            return True, "Login Success, Already Logged in"

    def send(self):
        # Navigate to the LinkedIn profile URL
        self.driver.get(self.profile_url)
        time.sleep(5)
        print("Waiting for document to be ready")
        page_state = self.driver.execute_script("return document.readyState;")
        while page_state != "complete":
            page_state = self.driver.execute_script("return document.readyState;")
        self.slide_down()
        print("Document is ready")
        time.sleep(5)

        # Minimize Messaging
        self.minimize_messaging_if_available()

        # Try sending a connection request
        connection_status = self.get_status()
        if connection_status in ["CONNECTED", "PENDING"]:
            return connection_status

        direct_connect_available = self._connect_from_button()
        if not direct_connect_available:
            self._connect_from_drop_down()

        time.sleep(2)
        if "Add a note to your invitation" in self.driver.page_source:
            if self.message:
                xpath_locator = "//button[@aria-label='Add a note']"
                button = self.driver.find_element(By.XPATH, xpath_locator)
                button.click()
                # Add the message
                # Then send
            else:
                xpath_locator = "//button[@aria-label='Send without a note']"
                button = self.driver.find_element(By.XPATH, xpath_locator)
                button.click()
        return True


class FollowUserCompany(ConnectionCommon):
    def __init__(self, driver, profile_url, message=None, email=None):
        super().__init__(driver, profile_url)
        self.message = message
        self.email = email
        self.last_shared_date = None
    
    def _follow_from_drop_down(self):
        self.click_more_action()
        xpath_locator = '//div[contains(@class, "artdeco-dropdown__item") and .//span[text()="Follow"]]'
        buttons = self.driver.find_elements(By.XPATH, xpath_locator)
        for button in buttons:
            try:
                button.click()
                return True
            except ElementNotInteractableException:
                pass
        return False
 
    def _follow_from_button(self):
        try:
            xpath_locator = '//button[contains(@aria-label, "Follow") and contains(@class, "pvs-sticky-header-profile-actions__action") and @type="button"]'
            button = self.driver.find_element(By.XPATH, xpath_locator)
            button.click()
            return True
        except NoSuchElementException:
            return False
 
    def send(self):
        self.driver.get(self.profile_url)
        time.sleep(5)
        print("Waiting for document to be ready")
        page_state = self.driver.execute_script('return document.readyState;')
        while page_state != 'complete':
            page_state = self.driver.execute_script('return document.readyState;')
        self.slide_down()
        print("Document is ready")
        time.sleep(5)
        self.minimize_messaging_if_available()
 
        connection_status = self.get_status()
        if connection_status in [ProfileState.PENDING]:
            return connection_status
       
        direct_follow_available = self._follow_from_button()
        if not direct_follow_available:
            self._follow_from_drop_down()
            time.sleep(5)
 
        # After following, navigate to the experience page
        self.navigate_to_experience_section()
 
        return True
 
    def navigate_to_experience_section(self):
        # Reload the profile URL with the /details/experience path to navigate to the experience page
        experience_url = f"{self.profile_url}/details/experience"
        self.driver.get(experience_url)
        time.sleep(5)  # Wait for the page to load
 
        print("Navigating to experience section")
   # Scroll down if necessary
        time.sleep(3)
 
        # Target the top container of the experience section and search for the most recent experience
        self.target_top_experience_container()
 
       
    def target_top_experience_container(self):
        try:
            company_elements = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/company/"]')
            company_profiles = [elem.get_attribute('href') for elem in company_elements]
    
            # Follow each company profile
            for profile_url in company_profiles:
                self.driver.get(profile_url)
                time.sleep(5)  # Wait for the page to load
    
                try:
                    # Find and click the "Follow" button
                    follow_button = self.driver.find_element(By.XPATH, '//button[contains(@class, "follow")]')
                    if follow_button.text.lower() == 'follow':
                        follow_button.click()
                        print(f'Followed {profile_url}')
                    else:
                        print(f'Already following {profile_url}')
                except Exception as e:
                    print(f'Could not follow {profile_url}: {e}')
    
                time.sleep(5)  
            
 
        except NoSuchElementException as e:
            print(f"Element not found: {e}")
        except Exception as e:
            print(f"An error occurred: {e}")























# Background task to send LinkedIn connection requests sequentially
async def send_linkedin_connections_sequentially():
    while profile_queue:
        profile = profile_queue.pop(0)
        profile_url = profile["profile_url"]

        # Call the send_linkedin_connection function with ConnectionRequest class
        send_linkedin_connection(profile_url)

        await asyncio.sleep(3)  # 1 minutes delay between requests (adjust as needed)


# Function to send LinkedIn connection request using the ConnectionRequest class
def send_linkedin_connection(profile_url: str):
    sync = SendingConnectionRequest(profile_url)
    sync.login("xxxx", "yyyy", cookies_location="cookies")

    try:

        connection_status = sync.send()
        if connection_status in ["CONNECTED", "PENDING"]:
            print(f"Already {connection_status} with {profile_url}")
        else:
            print(f"Connection request sent to {profile_url}")
    except Exception as e:
        print(f"Error sending request to {profile_url}: {e}")


# Function to add profile URLs to the queue and process them sequentially
async def process_csv_and_queue_requests(file: UploadFile):
    content = await file.read()
    reader = csv.DictReader(StringIO(content.decode("utf-8")))

    for row in reader:
        profile_data = {
            "profile_url": row.get("profile_url")  # Only profile_url from CSV
        }
        if profile_data["profile_url"]:
            profile_queue.append(profile_data)

    if profile_queue:
        asyncio.create_task(send_linkedin_connections_sequentially())
