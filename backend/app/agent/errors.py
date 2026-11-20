class NoCredentials(Exception):
    """The selected LLM provider has no API key; go straight to the scripted fallback."""


class RefusalError(Exception):
    """The model declined; hand off to a property manager."""
