"""Wallet domain errors."""


class WalletError(Exception):
    """Base class for wallet operation failures."""


class InsufficientFunds(WalletError):
    """Raised when a hold/debit would exceed the account's available balance."""


class AccountFrozen(WalletError):
    """Raised when spending against a frozen (abuse-held) account."""
