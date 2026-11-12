# leaf

A small EPUB reader for Linux desktops, styled like an e-ink screen: paper and ink
colors, square borders ruled in ink, and pages that turn without animation.

Python + GTK3 + WebKitGTK for a native (Wayland) window; books are rendered by
[foliate-js](https://github.com/johnfactotum/foliate-js).

## Features

- Paginated reading, one column or a two-page spread on wide windows (≥ 1400 px)
- Paper and ink themes (`#EEEDE8` / `#1C1C1A`); book text in Charter,
  interface in JetBrains Mono
- Contents sheet, text size, progress bar and location in the footer
- Remembers your place in every book; library of recent books
- Optional wood-tap sound on page turns (uses PipeWire's sample cache)
- EPUB scripts never run: the page enforces the strict Content Security Policy
  foliate-js requires, and external links open in your browser

## Install

Needs `python-gobject`, `gtk3` and `webkit2gtk-4.1` (Arch package names).

```sh
git clone --recurse-submodules git@github.com:VicAlexandre/leaf.git
cd leaf
make install          # links ~/.local/bin/leaf, registers it for EPUB files
```

`make install` creates symlinks, so a `git pull` also updates the installed reader.
`make uninstall` removes the link and the desktop entry.

## Use

```sh
leaf book.epub        # open a book
leaf                  # library of recent books
```

| Key | Reader | Library |
|---|---|---|
| `←` `→` `h` `l` space, wheel | turn pages | |
| `↑` `↓` `j` `k` | | select |
| `enter` | | open book |
| `t` | contents | |
| `+` `-` | text size | |
| `d` | paper / ink | paper / ink |
| `s` | page-turn sound | |
| `b` | library | |
| `o` | open file | open file |
| `q` | quit | quit |

Reading positions and settings live in `~/.local/state/leaf/library.json`.
Set `LEAF_DEBUG=1` to print the page's console messages.

## Layout

| Path | What |
|---|---|
| `leaf` | GTK window; serves `app/`, `foliate-js/` and the open book over a private `leaf://` scheme |
| `app/` | reader and library pages (HTML, CSS, JS) |
| `foliate-js/` | submodule, pinned to a known-good commit |
| `data/leaf.desktop` | desktop entry (`application/epub+zip`) |

## License

MIT, see [LICENSE](LICENSE). foliate-js is MIT-licensed by John Factotum.
