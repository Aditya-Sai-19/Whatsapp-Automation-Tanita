from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import re
import time
from typing import Callable, Optional

from playwright.sync_api import BrowserContext, Error, Page, TimeoutError, sync_playwright


LogFn = Callable[[str], None]


class WhatsAppNotReadyError(RuntimeError):
    pass


class WhatsAppSendError(RuntimeError):
    pass


class InvalidPhoneNumberError(ValueError):
    pass


@dataclass(frozen=True)
class SendResult:
    phone_digits: str
    pdf_path: Path
    success: bool


class WhatsAppBot:
    def __init__(
        self,
        profile_dir: Path,
        *,
        headless: bool = False,
        min_delay_seconds: int = 6,
        max_delay_seconds: int = 10,
    ):
        self.profile_dir = profile_dir
        self.headless = headless
        self.min_delay_seconds = min_delay_seconds
        self.max_delay_seconds = max_delay_seconds

        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def start(self, log: Optional[LogFn] = None) -> None:
        if log:
            log(f"Starting Chrome persistent session at: {self.profile_dir}")

        self.profile_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel="chrome",
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
            viewport=None,
        )

        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()

        self._page.set_default_timeout(60_000)

        self._ensure_whatsapp_loaded(log=log)

    def close(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            self._page = None

            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("WhatsAppBot is not started")
        return self._page

    def _ensure_whatsapp_loaded(self, log: Optional[LogFn]) -> None:
        page = self.page
        if log:
            log("Opening WhatsApp Web…")

        page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded")

        start_time = time.time()
        max_wait_seconds = 300

        while True:
            if time.time() - start_time > max_wait_seconds:
                raise WhatsAppNotReadyError(
                    "WhatsApp Web did not become ready in time. If this is the first run, scan the QR code."
                )

            try:
                if page.locator("[data-testid='qrcode'], canvas[aria-label*='Scan'], canvas[aria-label*='QR']").count() > 0:
                    if log:
                        log("Waiting for QR login (scan once; session is saved)…")
                    time.sleep(2)
                    continue

                ready = page.locator(
                    "[data-testid='chat-list-search'], div[role='textbox'][contenteditable='true'][data-tab]"
                ).count() > 0

                if ready:
                    if log:
                        log("WhatsApp Web is ready.")
                    return

            except Error:
                pass

            time.sleep(1)

    def _random_delay(self) -> float:
        return random.uniform(float(self.min_delay_seconds), float(self.max_delay_seconds))

    def send_pdf_to_phone(
        self,
        *,
        phone_digits: str,
        pdf_path: Path,
        log: Optional[LogFn] = None,
    ) -> SendResult:
        if not phone_digits.isdigit() or len(phone_digits) < 8 or len(phone_digits) > 15:
            raise InvalidPhoneNumberError(
                "Invalid phone number digits. Provide MobileNumber in the CSV with country code."
            )

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        page = self.page

        send_url = f"https://web.whatsapp.com/send?phone={phone_digits}"
        if log:
            log(f"Opening chat: {send_url}")

        page.goto(send_url, wait_until="domcontentloaded")

        self._handle_continue_to_chat(log=log)

        self._wait_for_chat_or_error(phone_digits=phone_digits, log=log)

        if log:
            log(f"Attaching PDF: {pdf_path.name}")

        self._attach_and_send_document(pdf_path=pdf_path, log=log)

        delay = self._random_delay()
        if log:
            log(f"Sent. Waiting {delay:.1f}s before next client…")
        time.sleep(delay)

        return SendResult(phone_digits=phone_digits, pdf_path=pdf_path, success=True)

    def _wait_for_chat_or_error(self, *, phone_digits: str, log: Optional[LogFn]) -> None:
        page = self.page

        invalid_number = page.locator("text=/phone number shared via url is invalid/i")
        not_on_whatsapp = page.locator("text=/isn't on whatsapp/i")

        try:
            page.wait_for_selector(
                "div[role='textbox'][contenteditable='true'][data-tab]",
                timeout=60_000,
            )
            return
        except TimeoutError:
            if invalid_number.count() > 0:
                raise InvalidPhoneNumberError(f"WhatsApp reports this phone number is invalid: {phone_digits}")
            if not_on_whatsapp.count() > 0:
                raise WhatsAppSendError(f"This number does not appear to be on WhatsApp: {phone_digits}")
            if log:
                log("Chat input not found yet; checking for WhatsApp load issues…")

        raise WhatsAppNotReadyError(
            "Could not open chat composer. WhatsApp Web may not be loaded/logged in, or UI changed."
        )

    def _handle_continue_to_chat(self, log: Optional[LogFn]) -> None:
        page = self.page

        continue_btn = page.get_by_role("button", name=re.compile(r"continue to chat", re.IGNORECASE))
        use_web_btn = page.get_by_role("link", name=re.compile(r"use whatsapp web", re.IGNORECASE))

        try:
            if continue_btn.is_visible(timeout=2_000):
                if log:
                    log("Clicking 'Continue to chat'…")
                continue_btn.click()

            if use_web_btn.is_visible(timeout=2_000):
                if log:
                    log("Clicking 'use WhatsApp Web'…")
                use_web_btn.click()
        except TimeoutError:
            return
        except Error:
            return

    def _focus_message_box(self) -> None:
        page = self.page
        composer = page.locator("div[role='textbox'][contenteditable='true'][data-tab]").first
        try:
            composer.wait_for(state="visible", timeout=10_000)
            composer.click()
        except TimeoutError as e:
            raise WhatsAppNotReadyError("Could not find the chat message box to focus.") from e

    def _click_attachment_button(self) -> None:
        page = self.page

        selectors = [
            "span[data-icon='attach']",
            "span[data-testid='attach-menu-plus']",
            "span[data-testid='clip']",
            "span[data-icon='attach-menu-plus']",
            "span[data-icon='plus']",
            "div[role='button'][aria-label*='Attach']",
            "div[role='button'][title*='Attach']",
            "button[aria-label*='Attach']",
            "button[title*='Attach']",
        ]

        last_err: Optional[Exception] = None
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=2_000)
                loc.click()
                return
            except (TimeoutError, Error) as e:
                last_err = e

        raise WhatsAppSendError("Could not find the attachment button on WhatsApp Web") from last_err

    def _click_document_option(self) -> None:
        page = self.page

        candidates = [
            page.locator("span[data-icon='attach-document']"),
            page.locator("div[role='button']:has-text('Document')"),
            page.locator("li[role='button']:has-text('Document')"),
            page.locator("div[role='button'][aria-label*='Document']"),
            page.locator("div[role='button'][title*='Document']"),
            page.locator("button[aria-label*='Document']"),
            page.locator("button[title*='Document']"),
        ]

        last_err: Optional[Exception] = None
        for loc in candidates:
            try:
                loc.first.wait_for(state="visible", timeout=3_000)
                loc.first.click()
                return
            except (TimeoutError, Error) as e:
                last_err = e

        raise RuntimeError("Could not find Document attachment option on WhatsApp Web") from last_err

    def _get_document_option_locator(self):
        page = self.page

        candidates = [
            page.locator("span[data-icon='attach-document']"),
            page.locator("div[role='button']:has-text('Document')"),
            page.locator("li[role='button']:has-text('Document')"),
            page.locator("div[role='button'][aria-label*='Document']"),
            page.locator("div[role='button'][title*='Document']"),
            page.locator("button[aria-label*='Document']"),
            page.locator("button[title*='Document']"),
        ]

        last_err: Optional[Exception] = None
        for loc in candidates:
            try:
                loc.first.wait_for(state="visible", timeout=3_000)
                return loc.first
            except (TimeoutError, Error) as e:
                last_err = e

        raise RuntimeError("Could not find Document attachment option on WhatsApp Web") from last_err

    def _attach_and_send_document(self, *, pdf_path: Path, log: Optional[LogFn]) -> None:
        page = self.page

        self._focus_message_box()
        self._click_attachment_button()

        doc_option = self._get_document_option_locator()

        try:
            with page.expect_file_chooser(timeout=3_000) as chooser_info:
                doc_option.click()
            chooser = chooser_info.value
            chooser.set_files(str(pdf_path))
        except TimeoutError:
            file_inputs = page.locator("input[type='file']")
            try:
                file_inputs.first.wait_for(state="attached", timeout=3_000)
            except TimeoutError as e:
                raise WhatsAppSendError("Document attachment input did not appear") from e

            found_candidate = False
            last_err: Optional[Exception] = None
            for i in range(file_inputs.count()):
                inp = file_inputs.nth(i)
                accept = (inp.get_attribute("accept") or "").lower()
                if "image" in accept or "video" in accept:
                    continue

                found_candidate = True
                try:
                    inp.set_input_files(str(pdf_path))
                    last_err = None
                    break
                except Error as e:
                    last_err = e

            if not found_candidate:
                raise WhatsAppSendError("Document attachment input did not appear")
            if last_err is not None:
                raise WhatsAppSendError("Failed to set PDF file into the attachment input") from last_err
        except Error as e:
            raise WhatsAppSendError("Failed to set PDF file into the attachment input") from e

        send_button = page.locator(
            "span[data-icon='send'], button[data-testid='compose-btn-send'], div[role='button'][aria-label*='Send']"
        )
        try:
            send_button.first.wait_for(state="visible", timeout=60_000)
            send_button.first.click()
        except TimeoutError as e:
            raise WhatsAppSendError("Send button did not appear for the document preview") from e

        dialog = page.locator("div[role='dialog']")
        if dialog.count() > 0:
            try:
                dialog.first.wait_for(state="detached", timeout=60_000)
            except TimeoutError:
                if log:
                    log("Document dialog did not close quickly; continuing.")
