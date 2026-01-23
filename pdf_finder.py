from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict


class PdfNotFoundError(FileNotFoundError):
    pass


class PdfAmbiguousMatchError(RuntimeError):
    pass


def _normalize_key(value: str) -> str:
    v = str(value).strip().lower()
    v = re.sub(r"[^a-z0-9]", "", v)
    return v


@dataclass(frozen=True)
class PdfMatch:
    client_name: str
    pdf_path: Path


class PdfFinder:
    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        if not self.reports_dir.exists():
            raise FileNotFoundError(f"Reports folder not found: {self.reports_dir}")
        if not self.reports_dir.is_dir():
            raise NotADirectoryError(f"Reports path is not a folder: {self.reports_dir}")

        self._index: Dict[str, Path] = {}
        self._build_index()

    def _build_index(self) -> None:
        pdfs = list(self.reports_dir.glob("*.pdf"))
        index: Dict[str, Path] = {}

        for p in pdfs:
            key = _normalize_key(p.stem)
            if not key:
                continue

            if key in index and index[key] != p:
                raise PdfAmbiguousMatchError(
                    f"Multiple PDFs normalize to the same name: '{index[key].name}' and '{p.name}'. "
                    "Rename files to be unique per client."
                )
            index[key] = p

        self._index = index

    def find_pdf_for_client(self, client_name: str) -> PdfMatch:
        key = _normalize_key(client_name)
        if not key:
            raise PdfNotFoundError("Client name is empty; cannot find PDF")

        path = self._index.get(key)
        if not path:
            raise PdfNotFoundError(
                f"No matching PDF found for client '{client_name}'. Expected a PDF in '{self.reports_dir}' "
                "whose filename matches the client name."
            )

        if not path.exists():
            raise PdfNotFoundError(f"Matched PDF does not exist: {path}")

        return PdfMatch(client_name=client_name, pdf_path=path)
