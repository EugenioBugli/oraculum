# Team logos (TV scoreboard)

Source: https://github.com/torchipeppo/RoboCupSPLTeamCommunicationMonitor/tree/ItalianOpen2026/resources/config
at commit `4b69159966467a4617203777a8697cfc9ae395fe` (downloaded 2026-10-22).

- `<number>.png` is the logo of team `<number>`; `teams.cfg` is the TCM's own number -> name list (unchanged).
- The PNGs were downscaled to at most 256 px per side (the originals are up to 5906 x 5906 px, 2.7 MB in all).
- Upstream git blob SHAs of the originals: 101 860798ae, 102 bc4be181, 12 abdc4b36, 19 6e008426, 24 5a0b4d93,
  29 78fbd2cc, 4 a6947ba7, 42 d4321edc, 8 1bae88e1, teams.cfg 4e503dac.

Licence: the repository is MIT, but its LICENSE states that it "does not apply to the subdirectories `deps` and
`resources`". The logos therefore have no stated licence; they are the marks of the teams. Use them only to name the
teams on the scoreboard.

The gateway lists every `<number>.png` here in `team_logos` of `GET /tv`; a `logo:` entry in `config/teams.yaml` maps
another number to a file (SPQR's 134 -> `19.png`).
