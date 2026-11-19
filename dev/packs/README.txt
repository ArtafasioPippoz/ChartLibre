The source of the extension packs that ship with ChartLibre: one folder per pack (pack.json and a folder per
plugin family). app/packages/<id>.clpack is built from it:

    .python/bin/python3 dev/tools/make_pack.py dev/packs/<id> app/packages

dev/tests/test_shipped_packs.py fails when a .clpack is older than its source. At start the application
installs each enabled pack's plugins in app/<family>/<id>/ (copies, ignored by git): edit the source here.
