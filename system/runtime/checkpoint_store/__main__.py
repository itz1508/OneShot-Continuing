"""Read-only execution notice for Host-owned checkpoint_store."""


def main() -> int:
    print("checkpoint_store is Host-managed; use the OneShot Host CLI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
