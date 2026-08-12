"""Error types for the draft renderer.

`DraftError` is the per-draft failure type: it means "this one sidecar is
unusable" and always routes that draft to `failed/` with an error file beside
it. `ConfigError` is a run-level failure: the renderer refuses to start.
"""

from __future__ import annotations


class DraftError(Exception):
    """A single draft is malformed, unsafe, or over a cap. Routes to failed/."""


class SidecarError(DraftError):
    """The sidecar JSON (or its body file) is malformed or unsafe."""


class RenderError(DraftError):
    """The draft parsed, but a validated field failed a rendering-time check."""


class ConfigError(Exception):
    """The renderer configuration is unsafe or incomplete -- do not run."""
