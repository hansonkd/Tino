#!/usr/bin/env bash

uvicorn bench_echo:fapi --host "localhost" --port "9999" --log-level error