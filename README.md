# WhatsApp PDF Sender (Local Desktop Automation)

A local Python desktop app that reads a CSV of clients and sends a matching PDF report to each client via **WhatsApp Web** using **Chrome** and a **persistent login profile**.

## What this does

- Reads `data/clients.csv` (columns: `ClientName`, `MobileNumber`)
- Finds a matching PDF in `reports/` whose filename matches the client name
- Opens WhatsApp Web in Chrome (you scan QR only once)
- Sends the PDF to each phone number using:

```
https://web.whatsapp.com/send?phone=<number>
```

## Folder structure (must keep this)

```
whatsapp_pdf_sender/
├── app.py
├── whatsapp_bot.py
├── pdf_finder.py
├── csv_loader.py
├── data/
│   └── clients.csv
├── reports/
│   └── <client_name>.pdf
├── browser_profile/
├── requirements.txt
└── README.md
```

## Setup (Windows)

1. Install **Python 3**.
2. Install **Google Chrome**.
3. Open a terminal in this folder and create a virtual environment:

```
python -m venv .venv
.venv\\Scripts\\activate
```

4. Install dependencies:

```
pip install -r requirements.txt
```

5. Install Playwright components:

```pip install -r requirements.txt
python -m playwright install
```

## Prepare your CSV

Edit `data/clients.csv` so it has exactly these columns:

- `ClientName`
- `MobileNumber`

Rules:

- `MobileNumber` must include country code.
- Digits only is recommended (a leading `+` is allowed).

Example:

```
ClientName,MobileNumber
John Doe,+919999999999
```

## Prepare your PDFs

Put PDFs in `reports/`.

Naming rule:

- The PDF filename (without `.pdf`) must match `ClientName`.
- Matching is case-insensitive and ignores spaces/symbols.

Examples:

- `ClientName = John Doe` can match `John Doe.pdf` or `john_doe.pdf`.

## Run

```
python app.py
```

## First-time WhatsApp QR login (only once)

- Click **Start Sending**.
- A Chrome window opens to WhatsApp Web.
- If you see a QR code, scan it using your phone:
  - WhatsApp on phone → Linked devices → Link a device
- The login session is saved inside `browser_profile/`.
- Next runs should not require scanning again (unless you log out).

## Notes / limitations

- This automation depends on WhatsApp Web UI selectors, which can change.
- Keep WhatsApp logged in and your phone connected.
- The app waits a random 6–10 seconds between sends.
