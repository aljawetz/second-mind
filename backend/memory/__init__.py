"""Agent memory — what Second Mind remembers about the student, as opposed to
the course index, which remembers the course. Design:
docs/superpowers/specs/2026-09-25-agent-memory-design.md.

Nothing in this package imports canvas.py, course_sync.py or main.py: it is
meant to be used by every agent (chat first, then the assignment explainer
and study artifacts), and to run on its own for the evaluation.
"""
