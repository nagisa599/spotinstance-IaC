#!/bin/bash
set -e
docker-compose run --rm latex
echo "Done: main.pdf"
