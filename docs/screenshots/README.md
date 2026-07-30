# Screenshots

Snapshots kept for visual review of a screen, so a change to it can be judged
against what it looked like before rather than from a description.

Regenerate any of them with `tools/shoot_screen.py`, which renders against a
throwaway data directory — it can never write demo content into real settings:

```
python tools/shoot_screen.py automations --demo automations --size 1280x860 --theme dark
python tools/shoot_screen.py automations --demo automations --size 860x420  --theme light
```

`860x420` is the app's minimum window size (`WINDOW_MIN_WIDTH`/`HEIGHT`), which is
where clipping shows up first. Both themes are kept because the tinted icon tiles
and the hairline dividers are the two things that go wrong when only one is checked.

The automations pair deliberately shows the busiest honest state: five rules across
four trigger kinds, the two-line "paused in this app only" row, and the 0.3.5 bridge
card. The same state is asserted structurally in
`tests/test_dpi_shell.py::test_the_automations_page_scrolls_instead_of_clipping_at_the_minimum_window`,
so the tests catch a regression and these show what it should look like. The larger
pair is taken at the same size the geometry check uses, so the picture and the
assertion describe one layout rather than two.
