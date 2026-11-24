# Contributing to ChartLibre

Thank you for looking. ChartLibre is a young project (version 0.2.0) and it
has had little testing by real people on real data, so **you do not need to
write code to help**. Most of what it needs right now is someone who uses it
and tells us what happens.

## Ways to help, from least to most effort

| You have... | You can... |
|---|---|
| 10 minutes | Download it, open a demo project, and say what confused you. |
| Your own data | Import it, plot it, and [open an issue](../../issues/new/choose) for anything wrong, confusing or missing. |
| Another tool you trust (R, SciPy, Origin, Prism) | Compare a fit, a test or a filter and report any difference ("Wrong result" issue form). |
| A Linux machine | Run `./ChartLibre.sh` and tell us what happens ("Platform report" form). Linux has never been tested properly. |
| Another language | Translate or proofread the interface (see below). No programming needed. |
| Packaging experience | winget, Scoop, Homebrew cask, AppImage or Flatpak. |
| Python / Qt / Matplotlib skills | Pick an issue labelled `good first issue` or `help wanted`. |

Not sure where to start? Look at the issues labelled
[`good first issue`](../../labels/good%20first%20issue). If none fits, ask in
[Discussions](../../discussions): saying "I'd like to help with X" is welcome.

## Reporting a problem

Use the issue forms: they ask for what we need. The most useful reports have:

1. **What you did**, step by step, from a fresh start.
2. **What you expected** and **what happened** (a screenshot helps).
3. **A small example project or data file**, if you can share one. A `.dhub`
   file is a SQLite database; you can strip it down to a few rows first.
4. Your **operating system** and the ChartLibre **version** (shown in the
   About / Credits window).

Please do not post data that is private, confidential or covered by an
agreement.

## Translating

The catalogue editor is built in: *Developer → Edit Localization* (open the
Developer launcher, `ChartLibre Developer`). The catalogues live in
`app/locales/<language>/LC_MESSAGES/` as `.po` files. Existing languages:
Arabic, German, Spanish, French, Hindi, Italian, Japanese, Portuguese.
Proofreading an existing language is as useful as adding a new one. Section 9
of [`dev/DEVELOPMENT.md`](dev/DEVELOPMENT.md) explains the format.

## Changing the code

Read [`dev/DEVELOPMENT.md`](dev/DEVELOPMENT.md) first. It describes the
architecture and the conventions the codebase actually follows.

### Set up

You need Python 3.14 or newer.

```bash
git clone <your fork's URL>
cd ChartLibre
python3 install.py                 # creates .venv and installs requirements.txt
.venv/bin/python3 ChartLibre.py    # on Windows: .venv\Scripts\python.exe ChartLibre.py
```

### Run the tests

```bash
python -m pytest dev/tests -q -n 6     # about 2 minutes
QT_QPA_PLATFORM=offscreen python -m pytest dev/tests -q -n 6   # on a machine with no display
```

To run only the tests of the area you touched, pass its file:
`python -m pytest dev/tests/test_analysis_clustering.py -q`.

### What a good pull request looks like

- **One change per pull request**, small enough to review in one sitting.
  If you plan something large, open an issue or a Discussion first so we can
  agree on the shape before you spend a week on it.
- **Tests** for new behaviour or a fixed bug. Calculations should be checked
  against a reference value (another tool, a textbook, or the NIST data
  already used in `dev/tests`).
- **The whole test suite passes** before you open the pull request.
- **No new dependency** without discussing it first; the installers bundle
  every library.
- **Interface text goes through the translation system**, not hard-coded
  (see `dev/DEVELOPMENT.md` §9).
- Say in the description **what** changed and **why**, and how you checked it.

You do not need to match anything beyond that: if a convention is missed we
will say so kindly, and fix small things ourselves.

### Using an AI assistant

ChartLibre was itself written mostly with an AI assistant, so you may use
one too. You remain responsible for what you submit: run the tests, read the
diff, and say in the pull request if an assistant wrote a substantial part.

## Licence

ChartLibre is [MIT](LICENSE). By submitting a contribution you agree that it
is released under the same licence.

## Conduct

Be patient and courteous. Beginners and non-native English speakers are the
people this project is for. Harassment, personal attacks and discrimination
are not tolerated; maintainers may remove comments or contributors that
break this.
