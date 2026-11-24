#set document(title: "ChartLibre — User Manual", author: "ChartLibre")
#set page(
  paper: "a4", margin: (x: 2.4cm, y: 2.4cm), numbering: "1",
  // Running header on every page but the cover: the application's icon on the
  // left, the title of the current chapter on the right, and a thin rule.
  // On the page where a chapter starts its own big title is there already, so
  // the chapter name is left out.
  header: context {
    let page-no = here().page()
    if page-no > 1 {
      let starts-here = query(heading.where(level: 1)).any(h => h.location().page() == page-no)
      let before = query(heading.where(level: 1).before(here()))
      let name = if starts-here or before.len() == 0 { none } else {
        let h = before.last()
        if h.numbering == none { h.body } else { [#numbering(h.numbering, ..counter(heading).at(h.location())) #h.body] }
      }
      set text(size: 9pt, fill: rgb("#5a6475"))
      grid(
        columns: (auto, 1fr),
        align: (left + horizon, right + horizon),
        image("logos/chartlibre.png", height: 0.6cm),
        if name != none { name },
      )
      v(-0.35em)
      line(length: 100%, stroke: 0.5pt + rgb("#c5ccd8"))
    }
  },
)
#set text(font: "New Computer Modern", size: 10.5pt, lang: "en")
#set par(justify: true, leading: 0.65em)
#set heading(numbering: "1.1")

#let version = "0.1.0"

#show heading.where(level: 1): it => {
  pagebreak(weak: true)
  v(0.4em)
  block(text(size: 20pt, weight: "bold", it.body))
  v(0.6em)
  line(length: 100%, stroke: 0.6pt + gray)
  v(0.6em)
}

#show heading.where(level: 2): it => {
  v(0.6em)
  block(text(size: 13.5pt, weight: "bold", it.body))
  v(0.2em)
}

#show heading.where(level: 3): it => {
  block(text(size: 11pt, weight: "bold", style: "italic", it.body))
}


#import "sections/helpers.typ": *

// ----------------------------------------------------------------------
// Cover: a colourful mosaic of charts and analyses
// ----------------------------------------------------------------------
#let card(name, w, h, fit: "cover") = box(
  width: w, height: h, radius: 7pt, clip: true,
  fill: white, stroke: 1.2pt + white.transparentize(30%),
  image("examples/" + name + ".png", width: 100%, height: 100%, fit: fit),
)

#page(margin: 0pt, header: none, footer: none, numbering: none,
  fill: gradient.linear(rgb("#0b1f3a"), rgb("#0d5c73"), rgb("#14a38b"), angle: 60deg),
)[
  // soft decorative circles
  #place(top + right, dx: 3cm, dy: -3cm, circle(radius: 6cm, fill: rgb("#ffffff").transparentize(92%)))
  #place(bottom + left, dx: -4cm, dy: 4cm, circle(radius: 7cm, fill: rgb("#f5b83d").transparentize(85%)))

  #pad(x: 1.6cm, top: 1.7cm)[
    #image("logos/chartlibre.png", height: 1.8cm)
    #v(0.3cm)
    #text(size: 44pt, weight: "bold", fill: white)[ChartLibre]
    #v(-0.2cm)
    #text(size: 18pt, fill: rgb("#f5d27a"), style: "italic")[User Manual]
    #v(0.35cm)
    #text(size: 11.5pt, fill: white.transparentize(15%))[
      Explore your data, run the analysis, publish the chart.
    ]
    #v(0.6cm)

    #grid(
      columns: (1fr, 1fr, 1fr), rows: (3.15cm, 3.15cm, 3.15cm, 3.15cm), gutter: 0.35cm,
      grid.cell(rowspan: 2, card("chart_surface_plot", 100%, 100%)),
      grid.cell(colspan: 2, rowspan: 2, card("analysis_pls", 100%, 100%)),
      card("chart_kaplan_meier", 100%, 100%), card("chart_violin_plot", 100%, 100%),
      grid.cell(rowspan: 2, card("chart_3d_bar_chart", 100%, 100%)),
      card("chart_contour_plot", 100%, 100%), card("chart_heatmap", 100%, 100%),
    )
  ]

  #place(bottom + left, dx: 1.6cm, dy: -1.3cm)[
    #text(size: 10pt, fill: white.transparentize(10%))[
      Application version #version \
      A desktop application for exploring data and building scientific charts
    ]
  ]
]

#pagebreak()
#outline(title: "Contents", indent: auto)

#include "sections/intro.typ"
#include "sections/start.typ"
#include "sections/window.typ"
#include "sections/data.typ"
#include "sections/charts.typ"
#include "sections/operations.typ"
#include "sections/analysis.typ"
#include "sections/statistics.typ"
#include "sections/output.typ"
#include "sections/settings.typ"
#include "sections/scripting.typ"
#include "sections/advanced.typ"
#include "sections/equivalents.typ"
