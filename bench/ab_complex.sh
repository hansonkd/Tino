#!/usr/bin/env bash

ab -p ./bench/post_complex.txt -T application/json -c 100 -n 100000 http://localhost:9999/fapi/echo/complex