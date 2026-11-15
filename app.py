"""
Black Hills Convergence researcher survey.

Flow: access code, then name / email / cell, then a text-message code,
then the survey, then done. The completed survey is emailed to the organizer.

Settings come from environment variables (set in Render, never in this file):
  BHC_ACCESS_CODE
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VERIFY_SERVICE_SID
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, NOTIFY_TO
  BHC_TEST_MODE=1   (local testing only: accepts the code 123456, no text sent)
"""
import base64
import csv
import json
import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import streamlit as st

from logo_b64 import LOGO_B64

HERE = Path(__file__).parent
TEST_MODE = os.getenv("BHC_TEST_MODE") == "1"
MAX_CODE_ATTEMPTS = 5
MAX_CODE_SENDS = 3
MAX_CODE_TRIES = 5
HELP = "Please write to bdemsey@demsey.com."

st.set_page_config(page_title="Black Hills Convergence", page_icon="🏔", layout="centered")

st.markdown(
    """
<style>
:root{--navy:#12294a;--green:#2e6b5b;}
.block-container{max-width:760px;padding-top:3rem;}
h1,h2,h3{color:#12294a;letter-spacing:-.02em;}
div.stButton>button,div[data-testid="stFormSubmitButton"]>button{background:#12294a;color:#fff;border:0;border-radius:999px;padding:.6rem 1.6rem;font-weight:600;}
div.stButton>button:hover,div[data-testid="stFormSubmitButton"]>button:hover{background:#0d1f3a;color:#fff;}
.note{color:#5b6b85;font-size:.95rem;}
.partlabel{color:#2e6b5b;font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:.8rem;margin-top:1.4rem;}
.testbanner{background:#fff4d6;border:1px solid #e6c667;border-radius:10px;padding:8px 12px;font-size:.9rem;}
.wm{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;z-index:999;overflow:hidden;}
.wm span{font-size:min(14vw,150px);font-weight:800;letter-spacing:.08em;color:rgba(120,130,145,.16);transform:rotate(-35deg);white-space:nowrap;user-select:none;}
</style>
<div class="wm"><span>DEMONSTRATION</span></div>
""",
    unsafe_allow_html=True,
)

QUESTIONS = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- twilio
def _twilio():
    sid, tok, svc = (os.getenv(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SERVICE_SID"))
    if not (sid and tok and svc):
        return None, None
    from twilio.rest import Client

    return Client(sid, tok), svc


def to_e164(raw):
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


def send_code(phone):
    if TEST_MODE:
        return True
    client, svc = _twilio()
    if not client:
        return False
    try:
        v = client.verify.v2.services(svc).verifications.create(to=phone, channel="sms")
        return v.status == "pending"
    except Exception:
        return False


def check_code(phone, code):
    if TEST_MODE:
        return code.strip() == "123456"
    client, svc = _twilio()
    if not client:
        return False
    try:
        c = client.verify.v2.services(svc).verification_checks.create(to=phone, code=code.strip())
        return c.status == "approved"
    except Exception:
        return False


def gate_available():
    return bool(os.getenv("BHC_ACCESS_CODE")) and (TEST_MODE or _twilio()[0] is not None)


# ---------------------------------------------------------------- results
def deliver(record, lines):
    """Email the result to the organizer and keep a local row. Returns True if emailed."""
    row = {"received": datetime.now(timezone.utc).isoformat(timespec="seconds"), **record}
    csv_path = HERE / "responses.csv"
    new = not csv_path.exists()
    try:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if new:
                w.writeheader()
            w.writerow(row)
    except Exception:
        pass

    host, to = os.getenv("SMTP_HOST"), os.getenv("NOTIFY_TO")
    if not (host and to):
        return False
    msg = EmailMessage()
    msg["Subject"] = f"Black Hills Convergence survey: {record['name']} ({record['email']})"
    msg["From"] = os.getenv("SMTP_USER", to)
    msg["To"] = to
    msg.set_content("\n".join(lines))
    try:
        with smtplib.SMTP_SSL(host, int(os.getenv("SMTP_PORT", "465"))) as s:
            s.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return True
    except Exception:
        return False


def ss(key, default=None):
    return st.session_state.get(key, default)


def header():
    c1, _ = st.columns([1, 2])
    c1.image(base64.b64decode(LOGO_B64), width=200)
    if TEST_MODE:
        st.markdown('<div class="testbanner">TEST MODE: the text code is 123456. No text message is sent.</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- pages
def page_gate():
    st.title("Welcome")
    st.write("Please enter the access code from your letter.")
    if not gate_available():
        st.error("This page is not available right now. " + HELP)
        return
    with st.form("gate"):
        code = st.text_input("Access code")
        go = st.form_submit_button("Continue")
    if go:
        if ss("attempts", 0) >= MAX_CODE_ATTEMPTS:
            st.error("Too many attempts. " + HELP)
        elif code.strip().lower() == os.getenv("BHC_ACCESS_CODE", "").strip().lower():
            st.session_state.step = "contact"
            st.rerun()
        else:
            st.session_state.attempts = ss("attempts", 0) + 1
            st.error("That code was not recognized. Please check your letter and try again.")


def page_contact():
    st.title("A little about you")
    st.write("We will text a confirmation code to your cell phone so that we know a real person is answering.")
    with st.form("contact"):
        name = st.text_input("Full name", value=ss("name", ""))
        email = st.text_input("Email address", value=ss("email", ""))
        cell = st.text_input("Cell number", value=ss("cell", ""))
        st.caption("Your name, email address and phone number will be used only to contact you about this effort.")
        go = st.form_submit_button("Text me the code")
    if go:
        phone = to_e164(cell)
        if not name.strip():
            st.error("Please enter your name.")
        elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()):
            st.error("Please enter a valid email address.")
        elif not phone:
            st.error("Please enter a 10-digit US cell number.")
        else:
            st.session_state.update(name=name.strip(), email=email.strip().lower(), cell=cell.strip(), phone=phone)
            if ss("sends", 0) >= MAX_CODE_SENDS:
                st.error("Too many codes requested. " + HELP)
            elif send_code(phone):
                st.session_state.sends = ss("sends", 0) + 1
                st.session_state.tries = 0
                st.session_state.step = "verify"
                st.rerun()
            else:
                st.error("We could not send the text. Please check the number. " + HELP)


def page_verify():
    st.title("Enter your code")
    st.write(f"We texted a 6-digit code to {ss('cell')}.")
    with st.form("verify"):
        code = st.text_input("Code", max_chars=6)
        go = st.form_submit_button("Confirm")
    c1, c2 = st.columns(2)
    if c1.button("Change my number"):
        st.session_state.step = "contact"
        st.rerun()
    if c2.button("Text me a new code"):
        if ss("sends", 0) >= MAX_CODE_SENDS:
            st.error("Too many codes requested. " + HELP)
        elif send_code(ss("phone")):
            st.session_state.sends = ss("sends", 0) + 1
            st.info("A new code is on its way.")
        else:
            st.error("We could not send the text. " + HELP)
    if go:
        if check_code(ss("phone"), code):
            st.session_state.step = "survey"
            st.rerun()
        else:
            st.session_state.tries = ss("tries", 0) + 1
            if ss("tries") >= MAX_CODE_TRIES:
                st.session_state.step = "contact"
                st.error("Too many wrong codes. " + HELP)
            else:
                st.error("That code did not match. Please try again.")


def page_survey():
    st.title("What would matter to you?")
    st.write(
        "Thank you for taking a few minutes. Black Hills State University, the Spearfish Economic Development "
        "Corporation and the City of Spearfish are preparing their strategic plans and are considering a "
        "cross-disciplinary research campus in Spearfish. Nothing is final. We would like to hear from leading "
        "researchers before anything is built."
    )
    st.write("There are no right answers. Skip anything you prefer not to answer. It takes about ten minutes.")
    n = 0
    with st.form("survey"):
        for part, note, items in QUESTIONS:
            st.markdown(f'<div class="partlabel">{part}</div>', unsafe_allow_html=True)
            if note:
                st.markdown(f'<div class="note">{note}</div>', unsafe_allow_html=True)
            for item in items:
                n += 1
                label, kind = item[0], item[1]
                opts = item[2].split("|") if len(item) > 2 else []
                key = f"q{n}"
                text = f"{n}. {label}"
                if kind == "t":
                    st.text_input(text, key=key, value=ss("name", "") if n == 1 else "")
                elif kind == "a":
                    st.text_area(text, key=key)
                elif kind == "c":
                    st.multiselect(text + " (choose all that apply)", opts, key=key)
                elif kind == "u":
                    st.multiselect(text, opts, key=key, max_selections=3)
                elif kind == "r":
                    st.radio(text, opts, index=None, key=key)
        go = st.form_submit_button("Submit")
    if go:
        finish()


def finish():
    lines = [
        f"Name: {ss('name')}",
        f"Email: {ss('email')}",
        f"Cell: {ss('cell')}  (text code confirmed)",
        "",
    ]
    record = {"name": ss("name"), "email": ss("email"), "cell": ss("cell"), "phone_confirmed": True}
    n = 0
    for part, note, items in QUESTIONS:
        lines.append(part)
        for item in items:
            n += 1
            a = ss(f"q{n}")
            a = "; ".join(a) if isinstance(a, list) and a else ("" if isinstance(a, list) else (a or ""))
            lines.append(f"{n}. {item[0]}\n   {a if a else '(no answer)'}")
            record[f"q{n}"] = a
        lines.append("")
    deliver(record, lines)
    st.session_state.step = "done"
    st.rerun()


def page_done():
    st.title("Thank you")
    st.write("Your answers have been received. We will be in touch only in the way you chose.")


header()
{"gate": page_gate, "contact": page_contact, "verify": page_verify, "survey": page_survey, "done": page_done}[ss("step", "gate")]()
