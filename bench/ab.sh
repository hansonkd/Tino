#!/usr/bin/env bash

ab -p ./bench/post_loc.txt -T application/json -c 10 -n 10000 http://localhost:9999/fapi/echo/simple