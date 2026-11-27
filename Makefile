VERSION = 2026.11.27-1
PREFIX ?= /usr
DESTDIR ?=
ARCH := $(shell dpkg --print-architecture 2>/dev/null || uname -m)

CC ?= cc
CFLAGS ?= -O2 -Wall
CPPFLAGS ?=
LDFLAGS ?=

BIN = $(PREFIX)/bin
SHAREZJS = $(PREFIX)/share/foo2zjs
CRDZJS = $(SHAREZJS)/crd/zjs
PPDDIR = $(PREFIX)/share/ppd/foo2zjs
MODELDIR = $(PREFIX)/share/cups/model
DOCDIR = $(PREFIX)/share/doc/printer-driver-foo2zjs-cp1025

PROGS = foo2zjs foo2zjs-dither zjsdecode
SCRIPTS = foo2zjs-wrapper foo2zjs-pstops

.PHONY: all clean install deb

all: $(PROGS) $(SCRIPTS)

jbig.o: jbig.c jbig.h jbig_ar.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ jbig.c

jbig_ar.o: jbig_ar.c jbig_ar.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ jbig_ar.c

foo2zjs.o: foo2zjs.c jbig.h zjs.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ foo2zjs.c

zjsdecode.o: zjsdecode.c jbig.h zjs.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ zjsdecode.c

foo2zjs: foo2zjs.o jbig.o jbig_ar.o
	$(CC) $(CFLAGS) -o $@ foo2zjs.o jbig.o jbig_ar.o $(LDFLAGS)

zjsdecode: zjsdecode.o jbig.o jbig_ar.o
	$(CC) $(CFLAGS) -o $@ zjsdecode.o jbig.o jbig_ar.o $(LDFLAGS)

foo2zjs-dither: foo2zjs-dither.c embedded_lut.h embedded_lut_pwm2.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ foo2zjs-dither.c -lm $(LDFLAGS)

foo2zjs-wrapper: foo2zjs-wrapper.in Makefile
	[ ! -f $@ ] || chmod +w $@
	sed < foo2zjs-wrapper.in > $@ \
	    -e 's@^PREFIX=.*@PREFIX=$(PREFIX)@' || (rm -f $@ && exit 1)
	chmod 0755 $@

foo2zjs-pstops: foo2zjs-pstops.sh
	cp foo2zjs-pstops.sh $@
	chmod 0755 $@

install: all
	install -d "$(DESTDIR)$(BIN)" "$(DESTDIR)$(CRDZJS)" "$(DESTDIR)$(PPDDIR)" "$(DESTDIR)$(MODELDIR)" "$(DESTDIR)$(DOCDIR)"
	install -m 0755 foo2zjs foo2zjs-dither zjsdecode foo2zjs-wrapper foo2zjs-pstops "$(DESTDIR)$(BIN)/"
	install -m 0644 crd/zjs/cp1025_purek_cmyk.icc crd/zjs/lut_cmyk_1x1.dat crd/zjs/lut_cmyk_pwm2.dat "$(DESTDIR)$(CRDZJS)/"
	gzip -cn -9 PPD/HP-LaserJet_Pro_CP1025nw.ppd > "$(DESTDIR)$(PPDDIR)/HP-LaserJet_Pro_CP1025nw.ppd.gz"
	chmod 0644 "$(DESTDIR)$(PPDDIR)/HP-LaserJet_Pro_CP1025nw.ppd.gz"
	ln -sf ../../ppd/foo2zjs/HP-LaserJet_Pro_CP1025nw.ppd.gz "$(DESTDIR)$(MODELDIR)/HP-LaserJet_Pro_CP1025nw.ppd.gz"
	install -m 0644 README.md CALIBRATION.md COPYING "$(DESTDIR)$(DOCDIR)/"

deb: all
	rm -rf .deb_stage
	$(MAKE) DESTDIR="$(CURDIR)/.deb_stage" PREFIX=/usr install
	install -d "$(CURDIR)/.deb_stage/DEBIAN"
	sed -e 's/@VERSION@/$(VERSION)/g' -e 's/@ARCH@/$(ARCH)/g' packaging/DEBIAN/control > "$(CURDIR)/.deb_stage/DEBIAN/control"
	install -m 0755 packaging/DEBIAN/postinst "$(CURDIR)/.deb_stage/DEBIAN/postinst"
	install -m 0755 packaging/DEBIAN/postrm "$(CURDIR)/.deb_stage/DEBIAN/postrm"
	dpkg-deb --build --root-owner-group "$(CURDIR)/.deb_stage" ../printer-driver-foo2zjs-cp1025_$(VERSION)_$(ARCH).deb
	rm -rf .deb_stage

clean:
	rm -rf *.o $(PROGS) $(SCRIPTS) .deb_stage
