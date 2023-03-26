#!/usr/bin/env bash

FIND="$(which find)"
if command -v gfind &> /dev/null
then
	FIND="$(which gfind)"
fi

eval "${FIND} secrets ! -name metal -delete"
