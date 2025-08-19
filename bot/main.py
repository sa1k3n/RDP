import argparse
import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Tuple

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver import FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.firefox import GeckoDriverManager


@dataclass
class Account:
    email: str
    password: str
    visa_type: Optional[str] = None


@dataclass
class BotConfig:
    login_url: str
    appointment_url: str
    center_value: str
    service_level_value: str
    destination_value: str
    pwnfox_xpi_path: Optional[str]
    firefox_binary_path: Optional[str]
    headless: bool
    implicit_wait_seconds: int
    page_load_timeout_seconds: int
    selector_wait_seconds: int
    max_workers: Optional[int]


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        base_path = getattr(sys, "_MEIPASS")
        candidate = os.path.join(base_path, relative_path)
        if os.path.exists(candidate):
            return candidate
    # fall back to CWD
    return os.path.abspath(relative_path)


def load_config(config_path: str) -> BotConfig:
    path = resolve_resource_path(config_path)
    data = load_json(path)
    return BotConfig(
        login_url=data["login_url"],
        appointment_url=data["appointment_url"],
        center_value=data["center_value"],
        service_level_value=data["service_level_value"],
        destination_value=data.get("destination_value", "Italy"),
        pwnfox_xpi_path=data.get("pwnfox_xpi_path"),
        firefox_binary_path=data.get("firefox_binary_path"),
        headless=bool(data.get("headless", False)),
        implicit_wait_seconds=int(data.get("implicit_wait_seconds", 5)),
        page_load_timeout_seconds=int(data.get("page_load_timeout_seconds", 60)),
        selector_wait_seconds=int(data.get("selector_wait_seconds", 25)),
        max_workers=(
            int(data["max_workers"]) if data.get("max_workers") not in (None, 0, "0") else None
        ),
    )


def parse_accounts_file(accounts_path: str) -> List[Account]:
    path = resolve_resource_path(accounts_path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Accounts file not found: {path}")

    accounts: List[Account] = []
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Support comma or tab separated
            if "," in line:
                parts = [p.strip() for p in line.split(",")]
            else:
                parts = [p.strip() for p in line.split()]  # whitespace split

            if len(parts) < 2:
                continue

            email = parts[0]
            password = parts[1]
            visa_type = parts[2] if len(parts) >= 3 else None
            accounts.append(Account(email=email, password=password, visa_type=visa_type))

    if not accounts:
        raise ValueError("No valid accounts found in accounts file.")
    return accounts


def create_firefox_driver(config: BotConfig) -> webdriver.Firefox:
    options = FirefoxOptions()
    if config.firefox_binary_path:
        options.binary_location = config.firefox_binary_path
    if config.headless:
        options.add_argument("-headless")

    # Prefer English UI for consistent selectors/text
    options.set_preference("intl.accept_languages", "en-US,en")

    # Keep a fresh temporary profile for isolation
    options.set_preference("browser.tabs.remote.autostart", True)

    service = FirefoxService(executable_path=GeckoDriverManager().install())
    driver = webdriver.Firefox(service=service, options=options)

    # Page load timeout and implicit waits
    driver.set_page_load_timeout(config.page_load_timeout_seconds)
    driver.implicitly_wait(config.implicit_wait_seconds)

    # Install PwnFox if provided
    if config.pwnfox_xpi_path:
        xpi_abs = os.path.abspath(config.pwnfox_xpi_path)
        if os.path.exists(xpi_abs):
            try:
                driver.install_addon(xpi_abs, temporary=True)
            except Exception:
                # Extension install is best-effort; carry on if it fails
                pass

    return driver


def wait_for_element_clickable(driver: webdriver.Firefox, locator: Tuple[str, str], timeout: int) -> object:
    return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator))


def wait_for_element_present(driver: webdriver.Firefox, locator: Tuple[str, str], timeout: int) -> object:
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located(locator))


def perform_login(driver: webdriver.Firefox, config: BotConfig, email: str, password: str) -> None:
    driver.get(config.login_url)

    # Fill username
    username_input = wait_for_element_present(driver, (By.CSS_SELECTOR, "#username"), config.selector_wait_seconds)
    username_input.clear()
    username_input.send_keys(email)

    # Fill password
    password_input = wait_for_element_present(driver, (By.CSS_SELECTOR, "#password"), config.selector_wait_seconds)
    password_input.clear()
    password_input.send_keys(password)

    # Submit
    login_button = wait_for_element_clickable(driver, (By.CSS_SELECTOR, "#kc-login"), config.selector_wait_seconds)
    login_button.click()

    # Wait until redirected to the main app domain
    try:
        WebDriverWait(driver, config.page_load_timeout_seconds).until(
            EC.url_contains("https://egy.almaviva-visa.it/")
        )
    except TimeoutException:
        # If redirect hook is slower, try navigating to appointment directly
        pass


def navigate_to_appointment(driver: webdriver.Firefox, config: BotConfig) -> None:
    # Navigate directly to appointment page
    driver.get(config.appointment_url)
    # Wait for Angular root to mount
    try:
        WebDriverWait(driver, config.selector_wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "app-root"))
        )
    except TimeoutException:
        # Some environments may render slower; continue and rely on later waits
        pass


def click_mat_select_by_label(driver: webdriver.Firefox, label_text: str, timeout: int) -> None:
    # Try several common Angular Material structures
    xpaths = [
        f"//mat-form-field[.//*[normalize-space(text())='{label_text}']]//div[contains(@class,'mat-select-trigger')]",
        f"//mat-form-field[.//*[contains(normalize-space(.), '{label_text}')]]//div[contains(@class,'mat-select-trigger')]",
        f"//label[normalize-space(text())='{label_text}']/ancestor::mat-form-field//div[contains(@class,'mat-select-trigger')]",
    ]
    last_exc = None
    for xp in xpaths:
        try:
            el = wait_for_element_clickable(driver, (By.XPATH, xp), timeout)
            el.click()
            return
        except Exception as exc:
            last_exc = exc
    # Fallback: open the first available mat-select
    try:
        el = wait_for_element_clickable(driver, (By.CSS_SELECTOR, "mat-select, div[role='combobox']"), timeout)
        el.click()
        return
    except Exception:
        if last_exc:
            raise last_exc
        raise


def choose_mat_option_by_text(driver: webdriver.Firefox, option_text: str, timeout: int) -> None:
    # Options live in an overlay panel
    option_xpath_exact = f"//mat-option//span[normalize-space(text())='{option_text}']"
    option_xpath_contains = f"//mat-option//span[contains(normalize-space(.), '{option_text}')]"
    try:
        el = wait_for_element_clickable(driver, (By.XPATH, option_xpath_exact), timeout)
        el.click()
        return
    except Exception:
        el = wait_for_element_clickable(driver, (By.XPATH, option_xpath_contains), timeout)
        el.click()


def set_trip_date_to_last_day_of_month(driver: webdriver.Firefox, timeout: int) -> None:
    # Open datepicker by label
    label_text = "Trip date"
    date_input_xpaths = [
        f"//mat-form-field[.//*[normalize-space(text())='{label_text}']]//input",
        f"//mat-form-field[.//*[contains(normalize-space(.), '{label_text}')]]//input",
        f"//label[normalize-space(text())='{label_text}']/ancestor::mat-form-field//input",
    ]
    date_input = None
    for xp in date_input_xpaths:
        try:
            date_input = wait_for_element_clickable(driver, (By.XPATH, xp), timeout)
            break
        except Exception:
            continue
    if not date_input:
        # Fallback to the first date input on the page
        date_input = wait_for_element_clickable(driver, (By.CSS_SELECTOR, "input[type='date'], input[matinput]"), timeout)

    date_input.click()

    # Compute last day of current month
    today = date.today()
    first_of_next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    last_day = first_of_next_month - timedelta(days=1)

    # Try selecting via calendar by day number in the current month view
    try:
        day_xpath = (
            "//div[contains(@class,'mat-datepicker-content') or contains(@class,'mat-calendar')]"
            "//td[not(contains(@class,'mat-calendar-body-disabled'))]//div[contains(@class,'mat-calendar-body-cell-content') and normalize-space(text())='" + str(last_day.day) + "']"
        )
        el = wait_for_element_clickable(driver, (By.XPATH, day_xpath), timeout)
        el.click()
        return
    except Exception:
        # As a fallback, try typing the date directly in common formats
        possible_formats = [
            f"{last_day.day:02d}/{last_day.month:02d}/{last_day.year}",  # dd/MM/yyyy
            f"{last_day.month:02d}/{last_day.day:02d}/{last_day.year}",  # MM/dd/yyyy
            str(last_day),  # yyyy-MM-dd
        ]
        for fmt in possible_formats:
            try:
                date_input.clear()
                date_input.send_keys(Keys.CONTROL, "a")
                date_input.send_keys(fmt)
                date_input.send_keys(Keys.TAB)
                return
            except Exception:
                continue
        # If all fail, do nothing; the flow may continue if date is optional


def fill_destination(driver: webdriver.Firefox, destination_text: str, timeout: int) -> None:
    # Find input by label
    label_text = "Destination"
    dest_xpaths = [
        f"//mat-form-field[.//*[normalize-space(text())='{label_text}']]//input",
        f"//mat-form-field[.//*[contains(normalize-space(.), '{label_text}')]]//input",
        f"//label[normalize-space(text())='{label_text}']/ancestor::mat-form-field//input",
    ]
    input_el = None
    for xp in dest_xpaths:
        try:
            input_el = wait_for_element_clickable(driver, (By.XPATH, xp), timeout)
            break
        except Exception:
            continue
    if not input_el:
        input_el = wait_for_element_clickable(driver, (By.CSS_SELECTOR, "input"), timeout)
    input_el.clear()
    input_el.send_keys(destination_text)


def tick_checkbox_by_text(driver: webdriver.Firefox, text_snippet: str, timeout: int) -> None:
    # Try to locate a mat-checkbox with the matching label text
    xpaths = [
        f"//mat-checkbox[.//*[contains(normalize-space(.), '{text_snippet}')]]",
        f"//label[contains(normalize-space(.), '{text_snippet}')]/ancestor::mat-checkbox",
    ]
    for xp in xpaths:
        try:
            wrapper = wait_for_element_present(driver, (By.XPATH, xp), timeout)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", wrapper)
            driver.execute_script("arguments[0].click();", wrapper)
            return
        except Exception:
            continue
    # Fallback: search for any checkbox input near text
    neighbors = driver.find_elements(By.XPATH, f"//*[contains(normalize-space(.), '{text_snippet}')]")
    for el in neighbors:
        try:
            checkbox = el.find_element(By.XPATH, ".//preceding::input[@type='checkbox'][1]")
            driver.execute_script("arguments[0].click();", checkbox)
            return
        except Exception:
            continue


def click_button_by_text(driver: webdriver.Firefox, button_text: str, timeout: int) -> None:
    xpaths = [
        f"//button[normalize-space(text())='{button_text}']",
        f"//button//*[normalize-space(text())='{button_text}']/ancestor::button",
        f"//button[contains(normalize-space(.), '{button_text}')]",
    ]
    for xp in xpaths:
        try:
            btn = wait_for_element_clickable(driver, (By.XPATH, xp), timeout)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            btn.click()
            return
        except Exception:
            continue
    raise NoSuchElementException(f"Button not found: {button_text}")


def fill_appointment_form(
    driver: webdriver.Firefox,
    config: BotConfig,
    visa_type_text: Optional[str],
) -> None:
    # Select center
    click_mat_select_by_label(driver, "Select the center", config.selector_wait_seconds)
    choose_mat_option_by_text(driver, config.center_value, config.selector_wait_seconds)

    # Select service level
    click_mat_select_by_label(driver, "Select service level", config.selector_wait_seconds)
    choose_mat_option_by_text(driver, config.service_level_value, config.selector_wait_seconds)

    # Select visa type (from account if provided)
    if visa_type_text:
        click_mat_select_by_label(driver, "Select the visa type", config.selector_wait_seconds)
        choose_mat_option_by_text(driver, visa_type_text, config.selector_wait_seconds)

    # Trip date: last day of current month
    set_trip_date_to_last_day_of_month(driver, config.selector_wait_seconds)

    # Destination: Italy
    fill_destination(driver, config.destination_value, config.selector_wait_seconds)

    # Terms and Privacy
    tick_checkbox_by_text(driver, "terms and conditions", config.selector_wait_seconds)
    tick_checkbox_by_text(driver, "privacy policy", config.selector_wait_seconds)

    # Check availability
    click_button_by_text(driver, "Check availability", config.selector_wait_seconds)


def worker(account: Account, config: BotConfig, index: int, start_barrier: Optional[threading.Barrier] = None) -> None:
    driver = None
    try:
        driver = create_firefox_driver(config)
        # Synchronize start across all workers to minimize timing differences
        if start_barrier is not None:
            try:
                start_barrier.wait(timeout=15)
            except Exception:
                pass

        perform_login(driver, config, account.email, account.password)
        navigate_to_appointment(driver, config)
        fill_appointment_form(driver, config, account.visa_type)
        # Keep the tab open for user to inspect results
    except Exception as exc:
        print(f"[Worker {index}] Error for {account.email}: {exc}")
    finally:
        # Intentionally do not close the driver to allow manual inspection
        pass


def run_concurrent(accounts: List[Account], config: BotConfig) -> None:
    threads: List[threading.Thread] = []
    max_workers = config.max_workers or len(accounts)
    active = 0
    # Barrier so all threads start actions nearly simultaneously
    start_barrier = threading.Barrier(parties=len(accounts)) if len(accounts) > 1 else None

    def start_thread(idx: int, acc: Account):
        t = threading.Thread(target=worker, args=(acc, config, idx, start_barrier), daemon=False)
        t.start()
        return t

    i = 0
    while i < len(accounts):
        while active < max_workers and i < len(accounts):
            t = start_thread(i + 1, accounts[i])
            threads.append(t)
            active += 1
            i += 1
        # Clean up finished
        still_running: List[threading.Thread] = []
        for t in threads:
            if t.is_alive():
                still_running.append(t)
            else:
                active -= 1
        threads = still_running

    # Wait for all to finish initial actions (best-effort short join)
    for t in threads:
        try:
            t.join(timeout=2.0)
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visa appointment bot for Almaviva Egypt")
    parser.add_argument("--accounts", default="accounts.txt", help="Path to accounts file (email,password[,visa_type])")
    parser.add_argument("--config", default="config.json", help="Path to config JSON file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    accounts = parse_accounts_file(args.accounts)
    print(f"Loaded {len(accounts)} account(s). Starting...")
    run_concurrent(accounts, config)
    print("All workers started. Browsers will remain open for inspection.")


if __name__ == "__main__":
    # Make webdriver-manager cache local to avoid elevated permissions on Windows
    os.environ.setdefault("WDM_LOCAL", "1")
    main()

