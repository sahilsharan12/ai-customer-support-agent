"""Run the dashboard against Uvicorn and an installed Chrome or Edge browser."""

import argparse
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory, TemporaryFile
from time import sleep
from urllib.error import URLError
from urllib.request import urlopen
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from backend import auth
from database.create_demo_db import DEMO_PROFILE, DEMO_ORDERS, create_demo_db


@contextmanager
def dashboard_server(environment):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    command = [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)]
    with (
        TemporaryFile(mode="w+", encoding="utf-8") as log,
        subprocess.Popen(command, env=environment, stdout=log, stderr=subprocess.STDOUT) as server,
    ):
        try:
            for _ in range(100):
                if server.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                try:
                    with urlopen(base + "/health", timeout=1):
                        break
                except URLError:
                    sleep(0.2)
            else:
                raise RuntimeError("Uvicorn did not start.")
            yield base
        finally:
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=10)


def verify(channel, screenshot=None):
    with TemporaryDirectory(prefix="support-browser-") as folder:
        root = Path(folder)
        orders = root / "orders.db"
        create_demo_db(orders)
        environment = {
            **os.environ,
            "SUPPORT_DATA_DIR": str(root / "support"),
            "ORDER_DB_PATH": str(orders),
            "JWT_SECRET_KEY": token_urlsafe(48),
            "DEMO_REFUNDS_ENABLED": "false",
        }
        admin_password = token_urlsafe(24)
        with patch.object(auth, "DB_PATH", root / "support" / "users.db"):
            auth.initialize_auth_database()
            admin = auth.register_user("browser-admin@example.test", admin_password)
            with auth.get_auth_connection() as connection:
                connection.execute("UPDATE users SET role = 'admin' WHERE user_id = ?", (admin["user_id"],))

        with dashboard_server(environment) as server, sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel=channel,
                args=["--disable-background-networking"],
                timeout=15_000,
            )
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 850})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(server + "/dashboard")
                register = page.locator("section.panel").filter(has=page.get_by_role("heading", name="New customer"))
                email = "browser-customer@example.test"
                password = token_urlsafe(24)
                register.get_by_label("Email").fill(email)
                register.get_by_label("Password").fill(password)
                register.get_by_role("button", name="Create account").click()
                expect(page.get_by_role("heading", name="Your support desk")).to_be_visible()
                account_id = page.locator("dt", has_text="Account ID").locator("xpath=following-sibling::dd[1]").inner_text()

                def sign_in(user_email, user_password):
                    page.get_by_role("button", name="Sign out").click()
                    login = page.locator("section.panel").filter(has=page.get_by_role("heading", name="Sign in", exact=True))
                    login.get_by_label("Email").fill(user_email)
                    login.get_by_label("Password").fill(user_password)
                    login.get_by_role("button", name="Sign in").click()

                sign_in("browser-admin@example.test", admin_password)
                expect(page.get_by_role("heading", name="Support overview")).to_be_visible()
                page.get_by_role("button", name="Link customer").click()
                page.get_by_label("Customer account ID").fill(account_id)
                page.get_by_label("Order profile ID").fill(DEMO_PROFILE)
                page.get_by_role("button", name="Link profile").click()
                expect(page.get_by_role("status")).to_have_text("Order profile linked.")

                sign_in(email, password)
                page.get_by_role("button", name="Orders", exact=True).click()
                expect(page.get_by_text(DEMO_ORDERS[0], exact=True)).to_be_visible()
                page.get_by_role("button", name="View", exact=True).first.click()
                expect(page.get_by_text("BRL 100", exact=True)).to_be_visible()
                if screenshot:
                    page.screenshot(path=screenshot)

                page.get_by_role("button", name="Returns", exact=True).click()
                page.get_by_label("Order ID").fill(DEMO_ORDERS[0])
                page.get_by_label("Reason").fill("Changed my mind")
                page.get_by_role("button", name="Submit return").click()
                expect(page.get_by_text("pending review", exact=True)).to_be_visible()

                page.get_by_role("button", name="Preferences", exact=True).click()
                page.get_by_role("button", name="Prefer concise replies").click()
                expect(page.get_by_text("concise", exact=True)).to_be_visible()
                page.get_by_role("button", name="Chat", exact=True).click()
                page.get_by_role("button", name="Open conversation").first.click()
                expect(page.get_by_text("I'll remember that you prefer concise replies.", exact=True)).to_be_visible()
                page.evaluate("""() => {
                    window.SpeechRecognition = class {
                        processLocally = false;
                        start() {
                            if (!this.processLocally) throw new Error("Expected on-device recognition");
                            this.onresult({results: [[{transcript: "A dictated message"}]]});
                        }
                    };
                    Object.defineProperty(window, "speechSynthesis", {value: {
                        getVoices: () => [{localService: true, lang: "en-US"}],
                        cancel: () => {},
                        speak: (reply) => { window.testSpokenReply = reply.text; },
                    }});
                    window.SpeechSynthesisUtterance = class {
                        constructor(text) { this.text = text; }
                    };
                }""")
                page.get_by_role("button", name="Dictate", exact=True).click()
                expect(page.get_by_label("Message", exact=True)).to_have_value("A dictated message")
                page.get_by_role("button", name="Read reply", exact=True).click()
                assert "prefer concise replies" in page.evaluate("window.testSpokenReply")
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                assert not errors, errors
            finally:
                browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="msedge", choices=["msedge", "chrome"])
    parser.add_argument("--screenshot")
    args = parser.parse_args()
    verify(args.channel, args.screenshot)
    print("Dashboard browser smoke passed.")
