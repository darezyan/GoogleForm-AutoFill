# Fill any Google Form a given number of times

import argparse
import datetime
import json
import math
import random
import re
import string
import sys
import time

import requests

# Question type codes used in the form's FB_PUBLIC_LOAD_DATA_
SHORT_ANSWER = 0
PARAGRAPH = 1
MULTIPLE_CHOICE = 2
DROPDOWN = 3
CHECKBOXES = 4
LINEAR_SCALE = 5
GRID = 7
PAGE_BREAK = 8
DATE = 9
TIME = 10
FILE_UPLOAD = 13

TEXT_TYPES = (SHORT_ANSWER, PARAGRAPH)

# Form setting: data[1][10][6] says whether the form collects email addresses
COLLECT_EMAILS_VERIFIED = 2
COLLECT_EMAILS_INPUT = 3

# Answer-rule ("response validation") codes: [type, subtype, args]
RULE_NUMBER, RULE_TEXT, RULE_REGEX, RULE_LENGTH, RULE_CHECKBOX = 1, 2, 4, 6, 7


class FormError(Exception):
    """A problem with the form itself (closed, needs sign-in, not a form link)."""


def normalize_link(link):
    link = link.strip()
    if link and not link.startswith(("http://", "https://")):
        link = "https://" + link
    return link


def hidden_input(html, name):
    match = re.search(r'<input[^>]*name="%s"[^>]*value="([^"]*)"' % re.escape(name), html)
    if not match:
        return None
    return match.group(1).replace("&quot;", '"').replace("&amp;", "&")


def load_form(link):
    """Fetches the form page and returns a dict describing the form:
    submit_url, questions, pages, fbzx, draft, collects_email."""

    resp = requests.get(normalize_link(link), timeout=30)  # also follows forms.gle short links
    if "accounts.google.com" in resp.url:
        raise FormError("This form needs a Google sign-in, so it can't be filled by this script.")
    if resp.url.endswith("closedform"):
        raise FormError("This form is closed and no longer accepts responses.")
    if resp.status_code in (404, 410):
        raise FormError("Form not found. Check the link.")
    resp.raise_for_status()

    match = re.search(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.+?\])\s*;\s*</script>", resp.text, re.S)
    if not match:
        raise FormError("Couldn't read the form. Use the form's share link (ending in /viewform, or a forms.gle link), not the edit link.")
    data = json.loads(match.group(1))

    # .../forms/d/e/<id>/viewform?... -> .../forms/d/e/<id>/formResponse
    submit_url = resp.url.split("?")[0].rsplit("/", 1)[0] + "/formResponse"

    settings = data[1][10] if len(data[1]) > 10 and data[1][10] else []
    collects_email = settings[6] if len(settings) > 6 else None
    if collects_email == COLLECT_EMAILS_VERIFIED:
        raise FormError("This form records verified emails, which needs a Google sign-in, so it can't be filled by this script.")

    questions = []
    pages = 1
    for item in data[1][1] or []:
        title, qtype = item[1], item[3]
        if qtype == PAGE_BREAK:
            pages += 1
            continue
        if qtype == FILE_UPLOAD:
            raise FormError("This form has a file upload question, which needs a Google sign-in.")
        if len(item) < 5 or not item[4]:
            continue  # section headers, images, videos

        for entry in item[4]:
            options = [o[0] for o in (entry[1] or []) if o and o[0]]
            name = title or ""
            if qtype == GRID and len(entry) > 3 and entry[3]:
                name = f"{name} [{entry[3][0]}]"
            rule = entry[4][0] if len(entry) > 4 and entry[4] and qtype in TEXT_TYPES + (CHECKBOXES,) else None
            flags = entry[7] if len(entry) > 7 and entry[7] else []
            questions.append({
                "id": entry[0],
                "title": name,
                "type": qtype,
                "options": options,
                "required": len(entry) > 2 and bool(entry[2]),
                "rule": rule,
                "has_time": bool(flags[0]) if qtype == DATE and len(flags) > 0 else False,
                "has_year": bool(flags[1]) if qtype == DATE and len(flags) > 1 else True,
            })

    return {
        "submit_url": submit_url,
        "questions": questions,
        "pages": pages,
        "fbzx": hidden_input(resp.text, "fbzx"),
        "draft": hidden_input(resp.text, "partialResponse"),
        "collects_email": collects_email == COLLECT_EMAILS_INPUT,
    }


def random_text():
    return "Sample " + "".join(random.choices(string.ascii_lowercase, k=6))


def random_email():
    return "test." + "".join(random.choices(string.ascii_lowercase + string.digits, k=8)) + "@example.com"


def rule_args(rule):
    args = rule[2] if len(rule) > 2 and isinstance(rule[2], list) else []
    return args


def text_for_rule(rule):
    """Makes up text that passes a text question's answer rule.
    Returns None for rules that can't be satisfied automatically (custom patterns)."""

    if not rule:
        return random_text()
    rtype, sub = rule[0], rule[1] if len(rule) > 1 else None
    args = rule_args(rule)

    if rtype == RULE_NUMBER:
        nums = []
        for a in args:
            try:
                nums.append(float(a))
            except (TypeError, ValueError):
                pass
        n = nums[0] if nums else 0
        if sub == 1:   value = n + 1                 # greater than
        elif sub == 2: value = n                     # greater or equal
        elif sub == 3: value = n - 1                 # less than
        elif sub == 4: value = n                     # less or equal
        elif sub == 5: value = n                     # equal to
        elif sub == 6: value = n + 1                 # not equal to
        elif sub == 7 and len(nums) > 1:             # between
            low, high = math.ceil(nums[0]), math.floor(nums[1])
            value = random.randint(low, high) if low <= high else nums[0]
        elif sub == 8 and len(nums) > 1: value = nums[1] + 1  # not between
        else:          value = random.randint(1, 100)  # any number / whole number
        return str(int(value)) if float(value).is_integer() else str(value)

    if rtype == RULE_TEXT:
        if sub == 100 and args:   return f"Sample {args[0]}"   # must contain
        if sub == 101:            return "Sample answer"       # must not contain
        if sub == 102:            return random_email()
        if sub == 103:            return "https://example.com"
        return random_text()

    if rtype == RULE_LENGTH:
        try:
            limit = int(args[0])
        except (IndexError, TypeError, ValueError):
            return random_text()
        if sub == 202: return random_text()[:max(limit, 1)]           # max length
        if sub == 203: return " ".join(random_text() for _ in range(limit // 13 + 2))  # min length
        return random_text()

    return None  # custom pattern (regex): needs a fixed answer


def checkbox_pick(options, rule):
    low, high = 1, len(options)
    if rule and rule[0] == RULE_CHECKBOX:
        try:
            n = int(rule_args(rule)[0])
        except (IndexError, TypeError, ValueError):
            n = None
        if n is not None:
            sub = rule[1]
            if sub == 200: low = min(max(n, 1), len(options))   # at least
            elif sub == 201: high = max(min(n, len(options)), 1)  # at most
            elif sub == 204: low = high = min(max(n, 1), len(options))  # exactly
    return random.sample(options, random.randint(low, max(low, high)))


def make_answer(question, overrides):
    """Returns the answer for one question. Fixed answers win;
    a list there means one of its values is picked at random each time."""

    if question["title"] in overrides:
        value = overrides[question["title"]]
        return random.choice(value) if isinstance(value, list) and value else value

    qtype, options = question["type"], question["options"]
    if qtype == CHECKBOXES:
        return checkbox_pick(options, question["rule"]) if options else None
    if qtype in TEXT_TYPES:
        return text_for_rule(question["rule"])
    if qtype == DATE:
        return datetime.datetime.now()
    if qtype == TIME:
        return datetime.datetime.now().time()
    if options:  # multiple choice, dropdown, scale, grid, and any newer choice type
        return random.choice(options)
    return None


def unanswerable(form, overrides):
    """Required questions the script can't answer by itself."""
    return [q["title"] for q in form["questions"]
            if q["required"] and q["title"] not in overrides and make_answer(q, overrides) is None]


def build_payload(form, overrides, email=None):
    payload = {}
    for q in form["questions"]:
        key = f"entry.{q['id']}"
        answer = make_answer(q, overrides)
        if answer is None:
            continue
        if q["type"] == DATE and isinstance(answer, datetime.datetime):
            if q["has_year"]:
                payload[key + "_year"] = answer.year
            payload[key + "_month"] = answer.month
            payload[key + "_day"] = answer.day
            if q["has_time"]:
                payload[key + "_hour"] = f"{answer.hour:02d}"
                payload[key + "_minute"] = f"{answer.minute:02d}"
        elif q["type"] == TIME and isinstance(answer, datetime.time):
            payload[key + "_hour"] = f"{answer.hour:02d}"
            payload[key + "_minute"] = f"{answer.minute:02d}"
        else:
            payload[key] = answer  # a list is sent as repeated keys (checkboxes)

    try:
        draft = json.loads(form["draft"]) if form["draft"] else [None, None, form["fbzx"]]
    except ValueError:
        draft = [None, None, form["fbzx"]]
    if form["collects_email"]:
        email = email or random_email()
        payload["emailAddress"] = email
        draft += [None] * max(0, 8 - len(draft))
        draft[6], draft[7] = email, 1

    payload["pageHistory"] = ",".join(str(i) for i in range(form["pages"]))
    payload["partialResponse"] = json.dumps(draft)
    if form["fbzx"]:
        payload["fbzx"] = form["fbzx"]
    return payload
