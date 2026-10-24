# Pinned DataTables extensions

MIT assets from npm (DateTime CSS compiled from its unmodified SCSS using Sass 1.93.2):
- datatables.net-searchbuilder 1.4.2
- datatables.net-searchbuilder-bs5 1.4.2
- datatables.net-datetime 1.5.2

Official sources: https://cdn.datatables.net/searchbuilder/1.4.2/ and
https://cdn.datatables.net/datetime/1.5.2/ . Loaded only on contracts.
Uses existing AdminKit bundled DataTables 1.13.4 and Buttons; does not load
another core, Bootstrap or jQuery. SearchBuilder minimum core is 1.10.0.
No new Buttons integration is required: the controller uses the searchBuilder option.

SearchBuilder 1.6.0 was rejected in browser tests: its object-valued datetime
i18n call is incompatible with bundled core 1.13.4. Use 1.4.2, tested with dates.

SearchBuilder JS is the upstream `.min.js` distribution under a stable `.js`
name. DateTime JS has trailing whitespace removed; its CSS is compiled from
SCSS. No functional vendor changes.
