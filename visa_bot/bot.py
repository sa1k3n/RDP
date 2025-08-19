import argparse
import concurrent.futures
import dataclasses
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import WebDriverWait


LOGIN_URL = (
    "https://egyiam.almaviva-visa.it/realms/oauth2-visaSystem-realm-pkce/protocol/openid-connect/auth?"
    "response_type=code&client_id=aa-visasys-public&state=R0llRzNmYTI5T09yQzdLMExkSWJ3MjBBUFBJeTVHY09NZDAyZzJ5bFd5OUpf"
    "&redirect_uri=https%3A%2F%2Fegy.almaviva-visa.it%2F&scope=openid%20profile%20email&"
    "code_challenge=kuI0awA4RpteV7Wc8ppV8h_NWUl8_daKHoOQiHy_HCg&code_challenge_method=S256&"
    "nonce=R0llRzNmYTI5T09yQzdLMExkSWJ3MjBBUFBJeTVHY09NZDAyZzJ5bFd5OUpf"
)
APPOINTMENT_URL = "https://egy.almaviva-visa.it/appointment"


@dataclasses.dataclass
class Account:
    email: str
    password: str
    visa_type: str
    center: str = "Cairo"
    service_level: str = "Standard - EGP 1750"


def read_accounts(file_path: str) -> List[Account]:
    accounts: List[Account] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                print(f"Skipping malformed line (need email,password,visa_type): {line}")
                continue
            email, password, visa_type = parts[:3]
            center = parts[3] if len(parts) >= 4 and parts[3] else "Cairo"
            service_level = parts[4] if len(parts) >= 5 and parts[4] else "Standard - EGP 1750"
            accounts.append(Account(email=email, password=password, visa_type=visa_type, center=center, service_level=service_level))
    return accounts


def build_firefox_options(profile_dir: Optional[str] = None, firefox_binary: Optional[str] = None) -> FirefoxOptions:
    options = FirefoxOptions()
    options.set_preference("intl.accept_languages", "en-US,en")
    options.set_preference("dom.webdriver.enabled", False)
    options.set_preference("useAutomationExtension", False)
    if profile_dir:
        options.set_preference("browser.download.dir", profile_dir)
    # Explicitly use headful mode to allow human inspection
    options.headless = False
    if firefox_binary:
        options.binary_location = firefox_binary
    return options


def maybe_install_extension(driver: webdriver.Firefox, xpi_path: Optional[str]) -> None:
    if not xpi_path:
        return
    if not os.path.exists(xpi_path):
        print(f"Extension XPI not found at: {xpi_path}")
        return
    try:
        driver.install_addon(xpi_path, temporary=True)
        print(f"Installed extension: {xpi_path}")
    except Exception as exc:
        print(f"Failed to install extension {xpi_path}: {exc}")


def wait_for(driver: webdriver.Firefox, condition, timeout: int = 30):
    return WebDriverWait(driver, timeout).until(condition)


def perform_login(driver: webdriver.Firefox, account: Account) -> None:
    driver.get(LOGIN_URL)
    wait_for(driver, EC.presence_of_element_located((By.ID, "username")))
    driver.find_element(By.ID, "username").clear()
    driver.find_element(By.ID, "username").send_keys(account.email)
    driver.find_element(By.ID, "password").clear()
    driver.find_element(By.ID, "password").send_keys(account.password)
    driver.find_element(By.ID, "kc-login").click()

    # Wait for redirect to main site (Angular app)
    try:
        wait_for(driver, EC.url_contains("egy.almaviva-visa.it"), timeout=60)
    except TimeoutException:
        # Still proceed; some environments might block redirects
        pass


def open_appointment_page(driver: webdriver.Firefox) -> None:
    driver.get(APPOINTMENT_URL)
    # Wait for Angular root to be present
    wait_for(driver, EC.presence_of_element_located((By.TAG_NAME, "app-root")))


def click_element_when_clickable(driver: webdriver.Firefox, locator: tuple, timeout: int = 30):
    element = wait_for(driver, EC.element_to_be_clickable(locator), timeout=timeout)
    element.click()
    return element


def select_mat_option_by_text(driver: webdriver.Firefox, label_text: str, option_text: str) -> None:
    # Open mat-select by its label
    select_trigger_xpath = (
        f"(//mat-form-field[.//*[normalize-space(text())='{label_text}']]//div[@role='combobox'])[1]"
    )
    click_element_when_clickable(driver, (By.XPATH, select_trigger_xpath))

    option_xpath = (
        f"//mat-option//span[contains(normalize-space(.), "
        f"'{option_text}') or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
        f"'{option_text.lower()}')][1]"
    )
    click_element_when_clickable(driver, (By.XPATH, option_xpath))


def set_destination(driver: webdriver.Firefox, value: str) -> None:
    input_xpath = "(//mat-form-field[.//*[contains(normalize-space(text()), 'Destination')]]//input)[1]"
    input_el = wait_for(driver, EC.presence_of_element_located((By.XPATH, input_xpath)))
    input_el.click()
    # Select all and overwrite
    input_el.send_keys(Keys.CONTROL, "a")
    input_el.send_keys(value)


def set_trip_date_to_last_day_of_month(driver: webdriver.Firefox) -> None:
    # Open the datepicker via toggle button near label 'Trip date'
    toggle_btn_xpath = (
        "(//mat-form-field[.//*[contains(normalize-space(text()), 'Trip date')]]//mat-datepicker-toggle//button)[1]"
    )
    try:
        click_element_when_clickable(driver, (By.XPATH, toggle_btn_xpath))
    except TimeoutException:
        # Fallback: click the input directly (if clicking opens the overlay)
        input_xpath = "(//mat-form-field[.//*[contains(normalize-space(text()), 'Trip date')]]//input)[1]"
        click_element_when_clickable(driver, (By.XPATH, input_xpath))

    # Compute last day of current month
    now = datetime.now()
    first_next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    last_day = first_next_month - timedelta(days=1)
    aria_label = last_day.strftime("%-d %B %Y") if os.name != "nt" else last_day.strftime("#d %B %Y").replace("#", str(int(last_day.strftime("%d"))))

    # Click the day cell by aria-label
    day_btn_xpath = f"//div[contains(@class,'mat-calendar')]//button[@aria-label='{aria_label}']"
    try:
        click_element_when_clickable(driver, (By.XPATH, day_btn_xpath))
    except TimeoutException:
        # Some environments use non-padded day names differently; try alternative without leading zeros handling
        alt_label = f"{int(last_day.strftime('%d'))} {last_day.strftime('%B %Y')}"
        alt_xpath = f"//div[contains(@class,'mat-calendar')]//button[@aria-label='{alt_label}']"
        click_element_when_clickable(driver, (By.XPATH, alt_xpath))


def check_by_label_contains(driver: webdriver.Firefox, label_snippet: str) -> None:
    xpath = (
        f"(//mat-checkbox[.//label[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
        f"'{label_snippet.lower()}')]]//label)[1]"
    )
    try:
        click_element_when_clickable(driver, (By.XPATH, xpath))
    except TimeoutException:
        # Fallback generic checkbox search
        alt_xpath = f"(//label[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{label_snippet.lower()}')])[1]"
        click_element_when_clickable(driver, (By.XPATH, alt_xpath))


def click_check_availability(driver: webdriver.Firefox) -> None:
    btn_xpath = (
        "//button[.//span[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'check availability')] or "
        "contains(translate(normalize-space(text()), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'check availability')]"
    )
    click_element_when_clickable(driver, (By.XPATH, btn_xpath))


def fill_appointment_form(driver: webdriver.Firefox, account: Account) -> None:
    select_mat_option_by_text(driver, "Select the center", account.center)
    select_mat_option_by_text(driver, "Select service level", account.service_level)
    select_mat_option_by_text(driver, "Select the visa type", account.visa_type)
    set_trip_date_to_last_day_of_month(driver)
    set_destination(driver, "Italy")
    check_by_label_contains(driver, "terms")
    check_by_label_contains(driver, "privacy")
    click_check_availability(driver)


def run_account_flow(account: Account, idx: int, xpi_path: Optional[str], firefox_binary: Optional[str], geckodriver_path: Optional[str]) -> None:
    profile_dir = tempfile.mkdtemp(prefix=f"visa_bot_profile_{idx}_")
    options = build_firefox_options(profile_dir, firefox_binary)
    service: Optional[FirefoxService] = None
    if geckodriver_path and os.path.exists(geckodriver_path):
        service = FirefoxService(executable_path=geckodriver_path)
    driver = webdriver.Firefox(options=options, service=service)
    try:
        maybe_install_extension(driver, xpi_path)
        perform_login(driver, account)
        open_appointment_page(driver)
        fill_appointment_form(driver, account)
        print(f"[{account.email}] Flow completed up to 'Check availability'.")
    except Exception as exc:
        print(f"[{account.email}] Error: {exc}")
    finally:
        # Keep the browser open for inspection for a short time
        time.sleep(2)
        # Do not quit immediately to allow the site to respond; comment next line if you want to keep windows open
        # driver.quit()
        pass


def main():
    parser = argparse.ArgumentParser(description="Visa appointment automation bot")
    parser.add_argument("--accounts-file", default="accounts.txt", help="Path to CSV file: email,password,visa_type[,center][,service_level]")
    parser.add_argument("--pwnfox-xpi", default=None, help="Optional path to PwnFox XPI to install in each session")
    parser.add_argument("--max-workers", type=int, default=None, help="Override max workers; defaults to number of accounts")
    parser.add_argument("--firefox-binary", default=os.environ.get("FIREFOX_BINARY"), help="Path to firefox.exe if not on PATH")
    parser.add_argument("--geckodriver", default=os.environ.get("GECKODRIVER"), help="Path to geckodriver.exe if Selenium Manager fails")
    args = parser.parse_args()

    accounts = read_accounts(args.accounts_file)
    if not accounts:
        print("No accounts found. Add lines as: email,password,visa_type[,center][,service_level]")
        sys.exit(1)

    max_workers = args.max_workers or len(accounts)
    print(f"Loaded {len(accounts)} account(s). Starting...")

    # Run all in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for idx, account in enumerate(accounts):
            futures.append(executor.submit(run_account_flow, account, idx, args.pwnfox_xpi, args.firefox_binary, args.geckodriver))
        print("All workers started. Browsers will remain open for inspection.")
        concurrent.futures.wait(futures)


if __name__ == "__main__":
    main()

