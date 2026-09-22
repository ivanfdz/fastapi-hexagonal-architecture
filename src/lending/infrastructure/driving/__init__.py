"""Driving adapters: the ways the outside world starts a use case.

Only one lives here today (``http``). The folder exists in the plural because the
architecture's payoff is that adding a second -- a CLI, a queue consumer, a
scheduled job that emails overdue members -- means writing a sibling package and
touching nothing else. Each would build a command, call a use case and render the
result in its own idiom.
"""
