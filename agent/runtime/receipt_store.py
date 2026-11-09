"""Compatibility API: one implementation lives in system.runtime.receipt_store.store."""

from system.runtime.receipt_store.store import (
    ReceiptForgeryError as ReceiptForgeryError,
    ReceiptStore as ReceiptStore,
    ReceiptStoreError as ReceiptStoreError,
)
