# Screenshots

Snapshots kept for visual review of a screen, so a change to it can be judged
against what it looked like before rather than from a description.

Regenerate any of them with `tools/shoot_screen.py`, which renders against a
throwaway data directory — it can never write demo content into real settings:

```
python tools/shoot_screen.py automations --demo automations --size 1280x860 --theme dark
python tools/shoot_screen.py automations --demo automations --size 860x420  --theme light
python tools/shoot_screen.py automations --demo rule-new   --size 860x420  --theme dark
python tools/shoot_screen.py automations --demo rule-edit  --size 1280x860 --theme light
```

`860x420` is the app's minimum window size (`WINDOW_MIN_WIDTH`/`HEIGHT`), which is
where clipping shows up first. Both themes are kept because the tinted icon tiles
and the hairline dividers are the two things that go wrong when only one is checked.

`journal` scrolls to the history card, which sits below the fold on any window size.
Its demo entries cover all four outcomes on purpose — including a run the user called
off, which must not be painted as a failure, and an entry whose rule has since been
deleted.

`rule-new` and `rule-edit` are the two states of the rule editor that differ in kind:
a new rule cannot be saved until it is named (the problem line and the disabled Save
are the point of the shot), and an existing one is deletable, may hold a scene, and
shows what happens to the background switch when the action is not a power one. The
`860×420` pair is where the pinned header and footer earn their keep.

The automations pair deliberately shows the busiest honest state: five rules across
four trigger kinds, the two-line "paused in this app only" row, and the 0.3.5 bridge
card. The same state is asserted structurally in
`tests/test_dpi_shell.py::test_the_automations_page_scrolls_instead_of_clipping_at_the_minimum_window`,
so the tests catch a regression and these show what it should look like. The larger
pair is taken at the same size the geometry check uses, so the picture and the
assertion describe one layout rather than two.
