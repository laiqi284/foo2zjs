#!/bin/sh

VERSION='$Id: foo2zjs-pstops-cp1025,v 2026.11.25 Exp $'

PROGNAME="$0"

usage() {
	cat <<EOF
NAME
    `basename "$PROGNAME"` - PostScript filter for foo2zjs-wrapper (CP1025 dedicated)

OPTIONS
    -h ydimpts	For rotate -r, y dimension points
    -r		Rotate 90 clockwise
    -n		Neuter CUPS cupsPSLevel2
    -D lvl	Debug level
EOF
	exit 1
}

error() {
	echo "`basename "$PROGNAME"`: $1" >&2
	exit 1
}

case `uname -s` in
Darwin|FreeBSD)	sed=gsed;;
*)		sed=sed;;
esac

DEBUG=0
ROTATE90=0
NIXCUPS=0
YDIMpoints=
while getopts "9ach:nwsmSprgdHD:Vh?" opt
do
	case $opt in
	h)	YDIMpoints="$OPTARG";;
	n)	NIXCUPS=1;;
	r)	ROTATE90=1;;
	D)	DEBUG="$OPTARG";;
	V)	echo "$VERSION"; exit 0;;
	\?)	usage;;
	*)	;;
	esac
done
shift `expr $OPTIND - 1`

if [ $NIXCUPS = 1 ]; then
    n='s#^[^/]*cupsPSLevel2#false#'
else
    n=
fi

if [ $ROTATE90 = 1 ]; then
    r="1i\\
	<< /Install {\\
	    0 $YDIMpoints translate\\
	    -90 rotate\\
	} >> setpagedevice\\
	"
else
    r=
fi

$sed \
    -e "$n" \
    -e "$r" \
    "$@"
