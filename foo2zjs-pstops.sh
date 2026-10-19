#!/bin/sh

VERSION='$Id: foo2zjs-pstops.sh,v 1.21 2013/07/31 17:41:47 rick Exp $'

PROGNAME="$0"

usage() {
	cat <<EOF
NAME
    `basename $PROGNAME` - Add PS code for foo2*-wrapper

SYNOPSIS
    `basename $PROGNAME` [options] [file]

DESCRIPTION
    Add PS code for foo2zjs-wrapper.

OPTIONS
    -9		Use new gs (ver >= 9.00)
    -h ydimpts	For rotate -r, y dimension points
    -r		Rotate 90 clockwise
    -a		Accurate Screens code
    -c		CIEColor
    -n		Neuter CUPS cupsPSLevel2
    -w		Well Tempered Screens code
    -s		Stochastic FM Halftone code (1x1 Micro-Dots)
    -m		Stochastic FM Halftone code (1x2 Micro-Doublets, Zero-ICM Vivid)
    -S		Stochastic FM Halftone code (2x2 Clustered Dots, Vivid Color)
    -D lvl	Debug level
EOF

	exit 1
}

#
#       Report an error and exit
#
error() {
	echo "`basename $PROGNAME`: $1" >&2
	exit 1
}

debug() {
	if [ $DEBUG -ge $1 ]; then
	    echo "`basename $PROGNAME`: $2" >&2
	fi
}

#
#	Use gsed instead of sed on Mac OSX
#
case `uname -s` in
Darwin)		sed=gsed;;
FreeBSD)	sed=gsed;;
*)		sed=sed;;
esac

#
#       Process the options
#
DEBUG=0
ROTATE90=0
ACCURATE=0
CIECOLOR=0
NIXCUPS=0
WTS=0
STOCH=0
STOCH12=0
STOCH2=0
GSVER=old
while getopts "9ach:nwsmSrD:Vh?" opt
do
	case $opt in
	9)	GSVER=gs9;;
	a)	ACCURATE=1;;
	c)	CIECOLOR=1;;
	h)	YDIMpoints="$OPTARG";;
	n)	NIXCUPS=1;;
	r)	ROTATE90=1;;
	s)	STOCH=1;;
	m)	STOCH12=1;;
	S)	STOCH2=1;;
	w)	WTS=1;;
	D)	DEBUG="$OPTARG";;
	V)	echo "$VERSION"; exit 0;;
	h|\?)	usage;;
	esac
done
shift `expr $OPTIND - 1`

if [ $NIXCUPS = 1 ]; then
    n='s#^[^/]*cupsPSLevel2#false#'
else
    n=
fi

if [ $ROTATE90 = 1 ]; then
	    # %%currentpagedevice /PageSize get\
	    # %%aload pop translate\
    r="1i\
	<< /Install {\
	    0 $YDIMpoints translate\
	    -90 rotate\
	} >> setpagedevice
	"
else
    r=
fi

if [ "$GSVER" = "old" ]; then
    ht='\
        <<\
            /AccurateScreens true\
            /HalftoneType 1\
            /HalftoneName (Round Dot Screen) cvn\
            /SpotFunction { 180 mul cos exch 180 mul cos add 2 div}\
            /Frequency 137\
            /Angle 37\
        >> sethalftone
    '
else
    # Standard Rosette (~145 LPI, Area=17 pixels, Balanced tone and smoothness)
    ht_145='\
	/SpotDot { dup mul exch dup mul add 1 exch sub } def\
	<<\
	    /HalftoneType 5\
	    /Cyan <<\
		/HalftoneType 1\
		/AccurateScreens false\
		/Frequency 145.521186\
		/Angle 104.036243\
		/SpotFunction /SpotDot load\
	    >>\
	    /Magenta <<\
		/HalftoneType 1\
		/AccurateScreens false\
		/Frequency 145.521186\
		/Angle 165.963757\
		/SpotFunction /SpotDot load\
	    >>\
	    /Yellow <<\
		/HalftoneType 1\
		/AccurateScreens false\
		/Frequency 150.0\
		/Angle 0\
		/SpotFunction /SpotDot load\
	    >>\
	    /Black <<\
		/HalftoneType 1\
		/AccurateScreens false\
		/Frequency 141.421356\
		/Angle 45\
		/SpotFunction /SpotDot load\
	    >>\
	    /Default <<\
		/HalftoneType 1\
		/AccurateScreens false\
		/Frequency 141.421356\
		/Angle 45\
		/SpotFunction /SpotDot load\
	    >>\
	>> /Default exch /Halftone defineresource sethalftone
    '

    # Ultra-Fine Rosette (~190 LPI, Area=10 pixels, ~40% smaller rosette flowers)
    ht_190='\
	/SpotDot { dup mul exch dup mul add 1 exch sub } def\
	<<\
	    /HalftoneType 5\
	    /Cyan <<\
		/HalftoneType 1\
		/AccurateScreens false\
		/Frequency 189.737\
		/Angle 108.435\
		/SpotFunction /SpotDot load\
	    >>\
	    /Magenta <<\
		/HalftoneType 1\
		/AccurateScreens false\
		/Frequency 189.737\
		/Angle 161.565\
		/SpotFunction /SpotDot load\
	    >>\
	    /Yellow <<\
		/HalftoneType 1\
		/AccurateScreens false\
		/Frequency 200.0\
		/Angle 0\
		/SpotFunction /SpotDot load\
	    >>\
	    /Black <<\
		/HalftoneType 1\
		/AccurateScreens false\
		/Frequency 212.132\
		/Angle 45\
		/SpotFunction /SpotDot load\
	    >>\
	    /Default <<\
		/HalftoneType 1\
		/AccurateScreens false\
		/Frequency 212.132\
		/Angle 45\
		/SpotFunction /SpotDot load\
	    >>\
	>> /Default exch /Halftone defineresource sethalftone
    '

    # Stochastic FM Screening (Pure 1x1 Void-and-Cluster Blue Noise FM, Micro-Dots)
    ht_stoch1='\
	<< /UseWTS false >> setuserparams\
	{ (/usr/share/foo2zjs/crd/stoch.ps) run } stopped {\
	    pop { (/tmp/foo2zjs_stoch.ps) run } stopped {\
		pop (stocht.ps) runlibfile\
	    } if\
	} if\
	userdict /settransfer { pop } bind put\
	userdict /setcolortransfer { pop pop pop pop } bind put\
    '

    # Stochastic FM Screening (2x2 Clustered FM, Maximum Toner Opacity & Vivid Color)
    ht_stoch2='\
	<< /UseWTS false >> setuserparams\
	{ (/usr/share/foo2zjs/crd/stoch2.ps) run } stopped {\
	    pop { (/tmp/foo2zjs_stoch2.ps) run } stopped {\
		pop (stoch2.ps) runlibfile\
	    } if\
	} if\
	userdict /settransfer { pop } bind put\
	userdict /setcolortransfer { pop pop pop pop } bind put\
    '

    # Stochastic FM Screening (1x2 Micro-Doublets, Zero-ICM Vivid Color)
    ht_stoch12='\
	<< /UseWTS false >> setuserparams\
	{ (/usr/share/foo2zjs/crd/stoch12.ps) run } stopped {\
	    pop { (/tmp/foo2zjs_stoch12.ps) run } stopped {\
		pop (stoch12.ps) runlibfile\
	    } if\
	} if\
	userdict /settransfer { pop } bind put\
	userdict /setcolortransfer { pop pop pop pop } bind put\
    '

    if [ $STOCH12 = 1 ]; then
	ht="$ht_stoch12"
    elif [ $STOCH2 = 1 ]; then
	ht="$ht_stoch2"
    elif [ $STOCH = 1 ]; then
	ht="$ht_stoch1"
    elif [ $WTS = 1 ]; then
	ht="$ht_190"
    else
	ht="$ht_145"
    fi
fi

if [ $STOCH12 = 1 ]; then
    if [ ! -r /usr/share/foo2zjs/crd/stoch12.ps ] && [ ! -r /tmp/foo2zjs_stoch12.ps ]; then
	PROGDIR=`dirname "$PROGNAME"`
	if [ -r "$PROGDIR/crd/zjs/stoch12.ps" ]; then
	    cp "$PROGDIR/crd/zjs/stoch12.ps" /tmp/foo2zjs_stoch12.ps 2>/dev/null
	fi
    fi
    w="/%%Page:[        ]*[     (]1[    )].*\$/ i\
	$ht
	"
elif [ $STOCH2 = 1 ]; then
    if [ ! -r /usr/share/foo2zjs/crd/stoch2.ps ] && [ ! -r /tmp/foo2zjs_stoch2.ps ]; then
	PROGDIR=`dirname "$PROGNAME"`
	if [ -r "$PROGDIR/crd/zjs/stoch2.ps" ]; then
	    cp "$PROGDIR/crd/zjs/stoch2.ps" /tmp/foo2zjs_stoch2.ps 2>/dev/null
	fi
    fi
    w="/%%Page:[        ]*[     (]1[    )].*\$/ i\
	$ht
	"
elif [ $STOCH = 1 ]; then
    if [ ! -r /usr/share/foo2zjs/crd/stoch.ps ] && [ ! -r /tmp/foo2zjs_stoch.ps ]; then
	PROGDIR=`dirname "$PROGNAME"`
	if [ -r "$PROGDIR/crd/zjs/stoch.ps" ]; then
	    cp "$PROGDIR/crd/zjs/stoch.ps" /tmp/foo2zjs_stoch.ps 2>/dev/null
	fi
    fi
    w="/%%Page:[        ]*[     (]1[    )].*\$/ i\
	$ht
	"
elif [ $WTS = 1 ]; then
    w="/%%Page:[        ]*[     (]1[    )].*\$/ i\
	<< /UseWTS false >> setuserparams \
	$ht
	"
elif [ $ACCURATE = 1 ]; then
    w="/%%Page:[        ]*[     (]1[    )].*\$/ i\
	<< /UseWTS false >> setuserparams \
	$ht
	"
else
    w=
fi

#
#	Main Program
#
$sed \
    -e "$w" \
    -e "$n" \
    -e "$r" \
    $@
