"""Compatibility API: one implementation lives in system.runtime.receipt_store.store."""

from system.runtime.receipt_store.store import (
    ReceiptStoreError as ReceiptStoreError,
    ReceiptForgeryError as ReceiptForgeryError,
    ReceiptStore as ReceiptStore,
)
