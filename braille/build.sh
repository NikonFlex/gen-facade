#!/bin/sh
set -eu
cd "$(dirname "$0")"
upstream/node_modules/.bin/esbuild viewer-entry.ts --bundle --format=iife \
    --global-name=genfacadeBraille --outfile=agent.js
