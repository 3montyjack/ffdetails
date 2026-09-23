"""Errors raised while fetching or recording details."""


class FfdetailsError(Exception):
    """Base error for ffdetails."""


class FetchError(FfdetailsError):
    """A source request failed."""


class ParseError(FfdetailsError):
    """A source payload could not be recorded as published."""
