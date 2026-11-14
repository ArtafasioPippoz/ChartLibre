#import "helpers.typ": *

= Analyses and charts as Python <scripting>

An analysis is a call. In the *SymPy workpad* (Tools), a script or the Python console of your choice, the same analyses the Tables menu offers run from one line, and what they make comes back as an object:

```python
result = Analysis("Are there differences?", "Birds", roles={"response": ["mass"], "group": ["species"]})
result.report_text        # the report as text; result.report is the same as HTML
result.tables             # the tables it wrote; result.table("name") gives one as a DataFrame
result.figures            # the figures it drew (their numbers)
result.code()             # the call that makes this analysis again
result.rerun(table="Other")   # the same analysis on another table with the same column names
```

An analysis with one main role takes the columns as a list: `Analysis("Statistics", "Birds", ["mass"])`. Parameters are keywords (`degree=2`), a model is `model="..."`, and `analysis_names()` and `describe_analysis("name")` say what exists and what each one accepts. The names are in English everywhere, in scripts too.

A chart is a call as well: `Chart("Scatter Plot", "Birds", ["mass"], x="length", title="Mass")` gives an object with `figure_id`, `code()` and `png(path)`.

== Keeping an analysis <scripting-keep>

*Project > History* lists every analysis run in the project. Pick one there, and:

/ *Copy as Python*: puts its call on the clipboard; with _All operations_ picked, a script with one call a line.
/ *Save as function...*: keeps it as a Python function of the project, with its table, columns and parameters as defaults: `compare()`, or `compare(table="Other")`. The workpad defines the project's functions for you and `functions()` lists them.
/ *More > Save settings...*: writes its settings to a JSON file (name, table, columns, parameters, model, the ChartLibre version). *Open settings...* shows the analysis' own window filled from such a file, to look at and press OK; in the workpad `Analysis.from_file("file.json")` runs it, on another table too: `Analysis.from_file("file.json", table="Other")`.
/ *More > Export script...*: a `.py` file that runs the picked operations (all of them) on a project given on the command line. *Run again* runs them once more in this project.

An analysis of a chart's series has no table to name, so it shows as a comment in a script and cannot be saved as a function.
