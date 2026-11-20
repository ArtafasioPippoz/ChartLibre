The source of the extension packs that ship with ChartLibre: one folder per pack (pack.json and a folder per
plugin family). app/packages/<id>.clpack is built from it:

    .python/bin/python3 dev/tools/make_pack.py dev/packs/<id> app/packages

dev/tests/test_shipped_packs.py fails when a .clpack is older than its source. At start the application
installs each enabled pack's plugins in app/<family>/<id>/ (copies, ignored by git): edit the source here.

Translations: Developer > Edit Localization has a catalogue list (ChartLibre, or one of these packs). A pack's
translation of a language is <pack>/locales/<language>/pack.po, written there by that editor; make_pack.py puts it in
the .clpack, and the application reads it once the pack is installed. Strings are those the pack's plugins pass to _()
or tr(), plus its name and description from pack.json.
