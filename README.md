# Google Form AutoFill
Fill a Google Form a chosen number of times — handy for testing your own forms with sample responses.

## Setup
```
pip install -r requirements.txt
```

## Usage
### In the browser
```
python app.py
```
Opens a page at http://127.0.0.1:8765 where you paste the link, set the count and press Start.

### In the terminal
```
python FormFiller.py
```
It asks for the form link and how many times to fill it. Or pass them directly:
```
python FormFiller.py <form_link> <count> [--answers answers.json] [--email you@example.com] [--delay 2] [--dry-run]
```

- Choice questions get a random valid option; text questions get sample text; date/time get today/now.
- `--answers` sets fixed answers by question title. A list means one is picked at random each time:
  ```json
  {"Name": "Test User", "Age group": ["18-24", "25-34"]}
  ```
- `--dry-run` reads the form and prints what would be sent, without submitting.
- Text answers follow the form's rules (numbers, emails, URLs, length). Questions with a custom pattern rule need a fixed answer; the app tells you which.
- If the form collects emails, your `--email` is used, or a test address if you leave it out.
- Forms that require a Google sign-in (verified emails, file uploads, one response per person) can't be filled.
