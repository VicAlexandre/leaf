# leaf: install by linking into ~/.local, so `git pull` updates the installed reader.
PREFIX  ?= $(HOME)/.local
BINDIR  := $(PREFIX)/bin
APPSDIR := $(PREFIX)/share/applications
HERE    := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.PHONY: install uninstall check

install: check
	install -d $(BINDIR) $(APPSDIR)
	ln -sfn $(HERE)/leaf $(BINDIR)/leaf
	install -m 644 $(HERE)/data/leaf.desktop $(APPSDIR)/leaf.desktop
	-update-desktop-database $(APPSDIR) 2>/dev/null
	-xdg-mime default leaf.desktop application/epub+zip
	@echo "leaf installed: $(BINDIR)/leaf -> $(HERE)/leaf"

uninstall:
	rm -f $(BINDIR)/leaf $(APPSDIR)/leaf.desktop
	-update-desktop-database $(APPSDIR) 2>/dev/null

check:
	@test -f $(HERE)/foliate-js/view.js || { echo "foliate-js missing: run 'git submodule update --init'"; exit 1; }
	@python3 -c "import gi; gi.require_version('Gtk','3.0'); gi.require_version('WebKit2','4.1')" \
		|| { echo "needs python-gobject, gtk3 and webkit2gtk-4.1"; exit 1; }
