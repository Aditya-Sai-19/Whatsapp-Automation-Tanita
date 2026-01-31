from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import List

import pandas as pd


class CsvValidationError(ValueError):
    pass


class InvalidPhoneNumberError(ValueError):
    pass


@dataclass(frozen=True)
class ClientRecord:
    client_name: str
    mobile_number_raw: str
    mobile_number_e164_digits: str
    sent: str


_REQUIRED_COLUMNS = ["ClientName", "MobileNumber"]
_PHONE_RE = re.compile(r"^\+?\d{8,15}$")


def _normalize_phone_to_e164_digits(phone: str) -> str:
    raw = str(phone).strip()
    if not raw:
        raise InvalidPhoneNumberError("MobileNumber is empty")

    raw = raw.replace("\u00a0", " ")
    raw = raw.strip()

    if raw.startswith("00"):
        raw = "+" + raw[2:]

    if raw.startswith("+"):
        cleaned = "+" + re.sub(r"\D", "", raw[1:])
    else:
        cleaned = re.sub(r"\D", "", raw)

    if not cleaned:
        raise InvalidPhoneNumberError("MobileNumber is empty")

    if not _PHONE_RE.match(cleaned):
        raise InvalidPhoneNumberError(
            "Invalid MobileNumber format. Use country code, digits only (optionally starting with +)."
        )

    return cleaned.lstrip("+")


def load_clients_csv(csv_path: Path) -> List[ClientRecord]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)

    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise CsvValidationError(
            f"CSV is missing required columns: {', '.join(missing)}. Required: {', '.join(_REQUIRED_COLUMNS)}"
        )

    # Ensure a Sent column exists; if not, initialize to "No" for all rows.
    if "Sent" not in df.columns:
        df["Sent"] = "No"
    # Normalize Sent values to canonical form (Yes/No)
    if "Sent" in df.columns:
        df["Sent"] = df["Sent"].astype(str).str.strip().str.capitalize()
        df["Sent"] = df["Sent"].where(df["Sent"].isin(["Yes", "No"]), other="No")

    records: List[ClientRecord] = []
    for idx, row in df.iterrows():
        name = str(row.get("ClientName", "")).strip()
        phone_raw = str(row.get("MobileNumber", "")).strip()

        if not name:
            raise CsvValidationError(f"Row {idx + 2}: ClientName is empty")

        try:
            phone_digits = _normalize_phone_to_e164_digits(phone_raw)
        except InvalidPhoneNumberError as e:
            raise InvalidPhoneNumberError(f"Row {idx + 2}: {e}") from e

        sent_val = str(row.get("Sent", "No")).strip()
        if sent_val.capitalize() not in {"Yes", "No"}:
            sent_val = "No"

        records.append(
            ClientRecord(
                client_name=name,
                mobile_number_raw=phone_raw,
                mobile_number_e164_digits=phone_digits,
                sent=sent_val.capitalize(),
            )
        )

    if not records:
        raise CsvValidationError("CSV contains no client rows")

    return records


def save_clients_csv(csv_path: Path, records: List[ClientRecord]) -> None:
    """Persist client records back to CSV, including Sent state.

    We write to a temporary file first and then atomically replace the
    original to avoid corrupting the source on failure.
    """
    import pandas as pd
    data = {
        "ClientName": [r.client_name for r in records],
        "MobileNumber": [r.mobile_number_raw for r in records],
        "Sent": [r.sent for r in records],
    }
    df = pd.DataFrame(data)

    tmp_path = csv_path.with_name(csv_path.name + ".tmp")
    df.to_csv(tmp_path, index=False)
    try:
        tmp_path.replace(csv_path)
    except Exception:
        # Fallback in case replace isn't available on the platform
        csv_path.write_text(tmp_path.read_text(encoding="utf-8"), encoding="utf-8")
        tmp_path.unlink(missing_ok=True)
