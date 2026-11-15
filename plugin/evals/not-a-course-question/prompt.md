---
description: Unrelated coding work must not touch the plugin (it is active in every session).
tags: [negative, baseline]
max_turns: 6
allowed_tools: [Skill]
---

Why does this React component crash with "Cannot read properties of undefined (reading 'map')"?

const List = ({ items }) => <ul>{items.map((i) => <li key={i}>{i}</li>)}</ul>;
