"""Ortak yardımcılar: zaman dilimi, User-Agent, kibar bekleme, HTTP istemcisi."""
from __future__ import annotations

import datetime as dt
import os
import random
import time

import httpx

TR_TZ = dt.timezone(dt.timedelta(hours=3))  # Türkiye: UTC+3, yaz saati yok

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# Playwright yalnızca yedek yöntem; ortamda özel Chromium yolu varsa CHROMIUM_PATH ile verilir
CHROMIUM_PATH = os.environ.get("CHROMIUM_PATH") or None


def now_tr() -> dt.datetime:
    return dt.datetime.now(TR_TZ)


def iso_now() -> str:
    return now_tr().isoformat(timespec="seconds")


def polite_sleep(lo: float = 1.0, hi: float = 3.0) -> None:
    """İstekler arasında 1-3 sn rastgele bekleme."""
    time.sleep(random.uniform(lo, hi))


def make_client(**headers) -> httpx.Client:
    h = {"User-Agent": USER_AGENT, "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"}
    h.update(headers)
    return httpx.Client(headers=h, timeout=40, follow_redirects=True)


class ScrapeError(RuntimeError):
    """Bir adım veri çekemediğinde fırlatılır; main.py akışı durdurup nedenini gösterir."""
