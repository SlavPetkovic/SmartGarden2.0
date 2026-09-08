"""Pure domain logic.

Nothing in this package performs I/O or imports from `drivers`, `storage` or
`web` (ARCH-4). That constraint is what makes the whole decision path testable
on a laptop with no hardware and no database.
"""

from smartgarden.core import errors, models, physics, units

__all__ = ["errors", "models", "physics", "units"]
